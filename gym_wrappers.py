# pep-action-space
# pep-observation-space
# BHDEnv

import numpy as np
import gym
from gym.spaces import Box, Dict
from collections import OrderedDict
from pepperoni import BridgeHoleDesign
from reinforcement_utils import _normalize_01, _normalize_angle


def observe_bridge_update(data, length = 20.0, height = 10.0, allowable_stress=200.0, as_dict = False):
    """Preprocess data and provide as an observation (dict of np array, shape (n,)).
    
    Arguments:
        data:  dict provided from BridgeHoleDesign.update(rld)
        length, width:  float >= 0
        allowable_stress:  maximum stress the bridge can take on
    
    Returns:
        Array of side 4 + 3*ld_length:
        Output[ 0:10] = gmass_rld
              [10:30] = points (flattened)
              [30]    = mass                 Always at [-4]
              [31]    = stress               Always at [-3]
              [32]    = mass_ratio (reward). Always at [-2]
              [34]    = stress_ratio.        Always at [-1]
        All values are preprocessed, normalized from 0 to 1 or -1, 1.
        mass_ratio = 1 means the bridge has no mass, mass_ratio = 0 means the bridge has no hole.
        stress_ratio = 1 means the bridge has no stress, stress_ratio < 0 means the bridge has exceeded the allowable stress.
    """
    max_radius = np.sqrt(length**2 + height**2)
    max_mass   = length*height
    gmass_rld = np.tanh(np.array(data['gmass_rld']))
    points_ld = _normalize_01(np.array(data['geometry_info']['positions_ld']),
                              b = max_radius)
    mass = _normalize_01(data['mass'], b = max_mass)
    stress = _normalize_01(data['sigma'], b = allowable_stress)
    mass_ratio = (max_mass - data['mass'])/max_mass
    stress_ratio = (allowable_stress - data['sigma'])/allowable_stress
    
    if as_dict:
        gym.logger.warn("gym_wrappers.observe_bridge_update as_dict is deprecated and untested.")
        
        out = OrderedDict()
        out['mass']        = np.array([mass])
        out['stress']      = np.array([stress])
        out['gmass_rld']   = gmass_rld
        out['points_ld']   = points_ld
        out['mass_ratio']  = np.array([mass_ratio])
        out['stress_ratio']= np.array([stress_ratio])
    else:
        out = np.concatenate((gmass_rld, points_ld.reshape(-1),
                             [mass, stress, mass_ratio, stress_ratio]))
    
    return out


def observation_space_box(ld_length = 10, ld_count = 3, extra_length = 4, low = -1.0, high = 1.0, as_dict = False):
    ''' A dictionary representing the observation space from `observe_bridge_update'.
    
    Arguments:
        ld_length:  integer >= 1, the number of leading dancers.
        ld_count:  integer >= 0, the number of variables of length ld count.
        extra_length:  integer >= 0, the number of extra variables
    Returns:
        Box of appropriate length, to match observe_bridge_update
        
        E.g. With gmass_rld shape (10), points_ld shape (10, 2),
             and extra values mass, stress, mass_ratio, stress_ratio,
             we have ld_length = 10, ld_count = 3, and extra_length = 4
             for an output Box shape (34,).
    '''
    if as_dict:
        gym.logger.warn("gym_wrappers.observe_bridge_update as_dict is deprecated and untested.")
        out = { 'mass' : Box(low = 0.0, high = 1.0, shape = [1]),
                'stress' : Box(low = 0.0, high = 1.0, shape = [1]),
                'points_ld' : Box(low = 0.0, high = 1.0, shape = [ld_length, 2]),
                'gmass_rld' : Box(low = -1, high = 1, shape = [ld_length]),
                'mass_ratio' : Box(low = 0.0, high = 1.0, shape = [1]),
                'stress_ratio' : Box(low = 0.0, high = 1.0, shape = [1]),
              }
        return Dict(out)
    else:
        return Box(low = low, high = high, shape = (ld_length * ld_count + extra_length, ))


class BHDEnv(gym.Env):
    """
    BridgeHoleDesign environment.
    See: https://github.com/openai/gym/blob/master/gym/core.py
        (Documentation shamelessly adapted from there.)
    
    Attributes:
        action_space: The Space object corresponding to valid actions
        observation_space: The Space object corresponding to valid observations
        reward_range: A tuple corresponding to the min and max possible rewards
        
    Methods:
        step:  Mapping action --> observation, reward, done, info 
        reset:  Returns observation of initial state of the space.
        render:  Renders the environment. Mode == 'human', 'rgb_array', or 'ansi' by convention.
        close:  Automatically run when garbage collection / exit.
        seed:  Set the seed for the environment's RNG/RNGs. Returns list of seed history.
    """
    
    def __init__(self, bridge = None,
                       length = 20.0,
                       height = 10.0,
                       allowable_stress = 200.0):
        
        self.__version__ = "0.1.0"
        
        # Set up bridge values
        self.length = length
        self.height = height
        self.allowable_stress = allowable_stress
        self.max_mass = self.length * self.height
        # self.reset sets self.bridge, used later
        self.reset(bridge = bridge)
        self.ld_length = len(self.bridge.rld)
        self.max_radius = np.sqrt(self.length**2 + self.height**2)
        
        # Set up values required for Env
        self.reward_range = (0, self.max_mass)
        self.action_space = gym.spaces.Box(low = 0, high = self.max_radius, shape = (self.ld_length,))
        self.observation_space = observation_space_box(ld_length = self.ld_length)

    def _get_ob(self,data):
        ob = observe_bridge_update(data=data, length = self.length, height = self.height,
                                   allowable_stress = self.allowable_stress)
        return ob

    def step(self, action):
        """Accepts an action and returns a tuple (observation, reward, done, info).
        
        Arguments:
            action (np.array): an action provided to the environment.
                Here, the actor performs gradient descent, so the 'action'
                is a vector to be added to rld.
            
        Returns:
            observation (dict): agent's observation of the current environment.
                See observe_bridge_update
            reward (float) : reward returned: observation['mass_ratio']
            done (boolean): whether the episode has ended, in which case further
                step() calls will return undefined results.
                True if observation['stress'] >= allowable_stress.
            info (dict): Empty dict; to be used for debugging and logging info.
                         
        """
        rld = self.bridge.rld
        data = self.bridge.update(rld + action)
        ob = self._get_ob(data)
        reward = ob[-2]
        done = ob[-1] <= 0
        info = {}
        
        return ob, reward, done, info


    def reset(self, bridge=None):
        """Resets the state of the environment and returns an initial observation.
        Returns: observation (object): the initial observation of the space.
        """
        self.bridge = bridge
        if self.bridge is None:
            self.bridge = BridgeHoleDesign()
        
        data = self.bridge.update(self.bridge.rld)
        ob = self._get_ob(data)
        return ob


    def render(self, mode='human'):
        """Renders the environment.
        
        The set of supported modes varies per environment. (And some
        environments do not support rendering at all.)
        
        Conventional modes:
        - human: render to the current display or terminal.
        - rgb_array: Return an numpy.ndarray with shape (x, y, 3).
        - ansi: Return a string (str) or StringIO.StringIO containing a
          terminal-style text representation.
        
        Arguments:
            mode (str): the mode to render with
        """
        raise NotImplementedError
    
        
