# Copyright 2017 Google Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""A collection of bridges between encoder and decoder. A bridge defines
how encoder information are passed to the decoder.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import abc
import six
import numpy as np

import tensorflow as tf
from tensorflow.python.util import nest

def _total_tensor_depth(tensor):
  """Returns the size of a tensor without the first (batch) dimension"""
  return np.prod(tensor.get_shape().as_list()[1:])

@six.add_metaclass(abc.ABCMeta)
class Bridge(object):
  """An abstract bridge class. A bridge defines how state is passed
  between encoder and decoder.

  All logic is contained in the `_create` method, which returns an
  initial state for the decoder.

  Args:
    encoder_outputs: A namedtuple that corresponds to the the encoder outputs.
    decoder_cell: The RNN cell used in the decoder.
  """
  def __init__(self, encoder_outputs, decoder_cell):
    self.encoder_outputs = encoder_outputs
    self.decoder_cell = decoder_cell
    self.batch_size = tf.shape(
        nest.flatten(self.encoder_outputs.final_state)[0])[0]

  def __call__(self):
    """Runs the bridge function.

    Returns:
      An initial decoder_state tensor or tuple of tensors.
    """
    return self._create()

  @abc.abstractmethod
  def _create(self):
    """ Implements the logic for this bridge.
    This function should be implemented by child classes.

    Returns:
      A tuple initial_decoder_state tensor or tuple of tensors.
    """
    raise NotImplementedError("Must be implemented by child class")


class ZeroBridge(Bridge):
  """A bridge that does not pass any information between encoder and decoder
  and sets the initial decoder state to 0. The input function is not modified.
  """
  def _create(self):
    zero_state = self.decoder_cell.zero_state(self.batch_size, dtype=tf.float32)
    return zero_state


class PassThroughBridge(Bridge):
  """Passes the encoder state through to the decoder as-is. This bridge
  can only be used if encoder and decoder have the exact same state size, i.e.
  use the same RNN cell.
  """
  def _create(self):
    nest.assert_same_structure(
        self.encoder_outputs.final_state,
        self.decoder_cell.state_size)
    return  self.encoder_outputs.final_state


class InitialStateBridge(Bridge):
  """A bridge that creates an initial decoder state based on the output
  of the encoder. This state is created by passing the encoder outputs
  through an additional layer to match them to the decoder state size.
  The input function remains unmodified.

  Args:
    encoder_outputs: A namedtuple that corresponds to the the encoder outputs.
    decoder_cell: The RNN cell used in the decoder.
    bridge_input: Which attribute of the `encoder_outputs` to use for the
      initial state calculation. For example, "final_state" means that
      `encoder_outputs.final_state` will be used.
    activation_fn: An optional activation function for the extra
      layer inserted between encoder and decoder. A string for a function
      name contained in `tf.nn`, e.g. "tanh".
  """
  def __init__(
      self,
      encoder_outputs,
      decoder_cell,
      bridge_input="final_state",
      activation_fn=None):
    super(InitialStateBridge, self).__init__(
        encoder_outputs, decoder_cell)

    if not hasattr(encoder_outputs, bridge_input):
      raise ValueError("Invalid bridge_input not in encoder outputs.")

    self._bridge_input = getattr(encoder_outputs, bridge_input)
    self._activation_fn = None
    if activation_fn is not None:
      self._activation_fn = getattr(tf.nn, activation_fn)

  def _create(self):
    # Concat bridge inputs on the depth dimensions
    bridge_input = nest.map_structure(
        lambda x: tf.reshape(x, [self.batch_size, _total_tensor_depth(x)]),
        self._bridge_input)
    bridge_input_flat = nest.flatten([bridge_input])
    bridge_input_concat = tf.concat(bridge_input_flat, 1)

    # Pass bridge inputs through a linear layer
    with tf.variable_scope("initial_state_bridge"):
      def map_fn(output_size):
        """Linear layer for bridge inputs"""
        return tf.contrib.layers.fully_connected(
            inputs=bridge_input_concat,
            num_outputs=output_size,
            activation_fn=self._activation_fn)

      initial_state = nest.map_structure(map_fn, self.decoder_cell.state_size)

    return initial_state
