import tensorflow as tf
from tensorflow.python.ops import array_ops
from tensorflow.python.ops import variable_scope as vs
from tensorflow.python.ops.math_ops import sigmoid
from tensorflow.python.ops.math_ops import tanh
from tensorflow.python.ops.rnn_cell import RNNCell, _linear

from mod_op import tf_mod


def phi(t, s, tau):
    # return ((t - s) % tau) / tau
    # mod = t - s
    # tf.while_loop(tf.greater(mod - tau, 0), body=lambda: mod - tau)
    # mod += tau
    # return mod / tau
    # return tf.mod(t - s, tau) / tau
    return tf_mod(t - s, tau) / tau


def time_gate_3(phase, r_on, leak_rate, training_phase, hidden_units):
    if not training_phase:
        leak_rate = 1.0
    new_phase = []
    for i in range(hidden_units):
        print('Initialize gate {}-th. (total is {}).'.format(i, hidden_units))
        new_phase.append(tf.case({tf.less(phase[i], 0.5 * r_on):
                                      lambda: 2.0 * phase[i] / r_on,
                                  tf.logical_and(tf.less(0.5 * r_on, phase[i]), tf.less(phase[i], r_on)):
                                      lambda: 2.0 - 2.0 * phase[i] / r_on},
                                 default=lambda: leak_rate * phase[i], exclusive=True))
    return tf.pack(new_phase)


# return tf.case({tf.less(phase, 0.5 * r_on): lambda: 2.0 * phase / r_on,
#                tf.logical_and(tf.less(0.5 * r_on, phase), tf.less(phase, r_on)):
#                    lambda: 2.0 - 2.0 * phase / r_on},
#               default=lambda: leak_rate * phase, exclusive=True)


def time_gate(phase, r_on, leak_rate, training_phase):
    return tf.cond(phase < 0.5 * r_on, lambda: tf.divide(tf.mul(2, phase), r_on),
                   lambda: tf.sub(2, tf.divide(tf.mul(2, phase), r_on)))


def time_gate_2(phase, r_on, leak_rate, training_phase):
    if phase < 0.5 * r_on:
        return 2 * phase / r_on
    elif 0.5 * r_on < phase < r_on:
        return 2 - 2 * phase / r_on
    if not training_phase:
        return phase
    return leak_rate * phase


# this is going to change with v0.13


class PhasedLSTMCell(RNNCell):
    def __init__(self, num_units, use_peepholes=True, r_on=0.05, training_phase=True,
                 leak_rate=0.001, activation=tanh):
        self._num_units = num_units
        self._activation = activation
        self._use_peepholes = use_peepholes
        self._r_on = r_on
        self._leak_rate = leak_rate  # only during training
        self._training_phase = training_phase

    @property
    def state_size(self):
        return self._num_units, self._num_units

    @property
    def output_size(self):
        return self._num_units

    def extract_time(self, inputs):
        return 1.0  # TODO: update it

    def __call__(self, inputs, state, scope=None):
        """ Long short-term phased memory cell (P-LSTM)."""
        with vs.variable_scope(scope or type(self).__name__):
            # Parameters of gates are concatenated into one multiply for efficiency.
            c_prev, h_prev = state
            concat = _linear([inputs, h_prev], 4 * self._num_units, True)
            # i = input_gate, j = new_input, f = forget_gate, o = output_gate
            i, j, f, o = array_ops.split(1, 4, concat)
            t = self.extract_time(inputs)
            # test.SESSION.run(tf.global_variables_initializer())
            tau = vs.get_variable('tau', shape=[self._num_units], dtype=inputs.dtype)
            s = vs.get_variable('s', shape=[self._num_units], dtype=inputs.dtype)

            phase = phi(t, s, tau)
            kappa = time_gate_3(phase, self._r_on, self._leak_rate, self._training_phase, self._num_units)

            w_o_peephole = None
            if self._use_peepholes:
                w_i_peephole = vs.get_variable('W_I_peephole', shape=[self._num_units], dtype=inputs.dtype)
                w_f_peephole = vs.get_variable('W_F_peephole', shape=[self._num_units], dtype=inputs.dtype)
                w_o_peephole = vs.get_variable('W_O_peephole', shape=[self._num_units], dtype=inputs.dtype)
                f += w_f_peephole * c_prev
                i += w_i_peephole * c_prev

            new_c_tilde = (sigmoid(f) * c_prev + sigmoid(i) * self._activation(j))
            new_c = kappa * new_c_tilde + (1 - kappa) * c_prev

            if self._use_peepholes:
                o += w_o_peephole * new_c

            new_h_tilde = sigmoid(o) * self._activation(new_c_tilde)
            new_h = kappa * new_h_tilde + (1 - kappa) * h_prev
            new_state = (new_c, new_h)
            return new_h, new_state
