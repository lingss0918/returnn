
import theano
import numpy
import os
from Log import log
from math import sqrt
from theano.compat.python2x import OrderedDict
import theano.tensor as T
import theano.compile


class Updater:

  @classmethod
  def initFromConfig(cls, config):
    import rnn
    kwargs = {
      "gradient_clip": config.float('gradient_clip', -1),
      "adagrad": config.bool('adagrad', False),
      "adadelta": config.bool('adadelta', False),
      "adasecant": config.bool('adasecant', False),
      "adam": config.bool('adam', False),
      "max_norm" : config.float('max_norm', 0.0),
      "adadelta_decay": config.float('adadelta_decay', 0.90),
      "adadelta_offset": config.float('adadelta_offset', 1e-6),
      "update_multiple_models": config.int('update_multiple_models', 0),
      "update_multiple_models_average_step": config.int('update_multiple_models_average_step', 0),
      "momentum": config.float("momentum", 0),
      "nesterov_momentum": config.float("nesterov_momentum", 0),
      "momentum2": config.float("momentum2", 0),
      "rmsprop": config.float("rmsprop", 0) }
    return cls(**kwargs)

  @classmethod
  def initRule(cls, rule, **kwargs):
    kwargs.setdefault('momentum', 0)
    kwargs.setdefault('nesterov_momentum', 0)
    kwargs.setdefault('momentum2', 0)
    kwargs.setdefault('gradient_clip', -1)
    kwargs.setdefault('adadelta_decay', 0.90)
    kwargs.setdefault('adadelta_offset', 1e-6)
    kwargs.setdefault('adagrad', False)
    kwargs.setdefault('adadelta', False)
    kwargs.setdefault('adasecant', False)
    kwargs.setdefault('adam', False)
    kwargs.setdefault('max_norm', 0.0)
    kwargs.setdefault('rmsprop', 0)
    if rule != "default":
      kwargs[rule] = True
    return cls(**kwargs)

  def __init__(self, momentum, nesterov_momentum, momentum2, gradient_clip, adagrad, adadelta, adadelta_decay, adadelta_offset, max_norm, adasecant, adam, rmsprop, update_multiple_models=0, update_multiple_models_average_step=0):
    """
    :type momentum: float
    :type nesterov_momentum: float
    :type momentum2: float
    :type gradient_clip: float
    :type adagrad: bool
    :type adadelta: bool
    :type rmsprop: float
    """
    self.rng = numpy.random.RandomState(0101)
    self.momentum = momentum
    self.nesterov_momentum = nesterov_momentum
    self.momentum2 = momentum2
    self.gradient_clip = gradient_clip
    self.max_norm = max_norm
    self.adagrad = adagrad
    self.adadelta = adadelta
    self.adasecant = adasecant
    self.adam = adam
    self.rmsprop = rmsprop
    self.adadelta_decay = adadelta_decay
    self.adadelta_offset = adadelta_offset
    self.update_multiple_models = update_multiple_models
    self.update_multiple_models_average_step = update_multiple_models_average_step
    self.params = {}
    self.pid = -1
    assert not (self.adagrad and self.adadelta and self.adasecant and self.adam)
    if self.adadelta:
      self.momentum = 0.0
      self.nesterov_momentum = 0.0
      self.momentum2 = 0.0
      print >> log.v4, "using adadelta with decay", self.adadelta_decay, ", offset", self.adadelta_offset
    if self.adagrad:
      print >> log.v4, "using adagrad"
    if self.momentum:
      print >> log.v4, "using momentum %f" % self.momentum
    if self.nesterov_momentum:
      print >> log.v4, "using simplified nesterov momentum %f" % self.nesterov_momentum
    if self.momentum2:
      print >> log.v4, "using reverted momentum %f" % self.momentum2
    if self.gradient_clip > 0:
      print >> log.v4, "using gradient clipping %f" % self.gradient_clip
    if self.rmsprop:
      print >> log.v4, "using RMSProp with rho = %f" % self.rmsprop

  def initVars(self, network, net_param_deltas):
    """
    Initializes the Theano shared variables.
    This should be called in the process where you want to do the updating.
    All further calls must be from the same process.
    The network.gparams must be created in the same process.
    :type network: Network.LayerNetwork
    :type net_param_deltas: dict[theano.compile.sharedvalue.SharedVariable,theano.Variable] | None
    """
    assert not self.isInitialized
    self.pid = os.getpid()
    self.network = network
    if net_param_deltas is not None:
      self.net_train_param_deltas = net_param_deltas
    else:
      self.net_train_param_deltas = {p : theano.shared(numpy.zeros(p.get_value(borrow=True,
                                                                              return_internal_type=True).shape,
                                                                  dtype=theano.config.floatX))
                                     for p in network.train_params_vars}
      " :type: dict[theano.compile.sharedvalue.SharedVariable,theano.compile.sharedvalue.SharedVariable] "
    self.learning_rate_var = theano.shared(value=numpy.cast[theano.config.floatX](0), name="learning_rate")
    " :type: theano.compile.sharedvalue.SharedVariable "
    self.i = theano.shared(numpy.float32(network.update_step), name="updater_i")

    if self.momentum > 0:
      self.deltas = {p: theano.shared(
                     value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
                                       dtype=theano.config.floatX), borrow=True,
                     name="deltas_%s" % p)
                     for p in network.train_params_vars}

    if self.adagrad:
      self.accu = {}
      for p in self.network.train_params_vars:
        shape = p.get_value(borrow=True, return_internal_type=True).shape
        #scale = numpy.sqrt(12. / numpy.sum(shape))
        #values = numpy.asarray(self.rng.normal(loc=0.0, scale=scale, size=shape), dtype=theano.config.floatX)
        #values = p.get_value()
        values = numpy.zeros(shape, dtype=theano.config.floatX)
        self.accu[p] = theano.shared(value=values)

      #self.accu = {p: theano.shared(
      #               value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
      #                                 dtype=theano.config.floatX), borrow=True, name="accu_%s " % p)
      #            for p in self.network.train_params_vars}
      #self.sqrsum = {p: theano.shared(
      #               value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
      #                                 dtype=theano.config.floatX), borrow=True,
      #               name="sqrsum_%s " % p)
      #               for p in self.network.train_params_vars}
    if self.adadelta:
      # http://arxiv.org/pdf/1212.5701v1.pdf
      self.eg2 = {p: theano.shared(value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
                                                     dtype=theano.config.floatX))
                  for p in self.network.train_params_vars} #E[g^2]
      self.edx2 = {p: theano.shared(value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
                                                      dtype=theano.config.floatX))
                  for p in self.network.train_params_vars} #E[\delta x^2]
      self.dx = {p: theano.shared(value=numpy.zeros(p.get_value(borrow=True, return_internal_type=True).shape,
                                                    dtype=theano.config.floatX))
                  for p in self.network.train_params_vars} #\delta x

  @property
  def isInitialized(self):
    return self.pid >= 0

  def setNetParamDeltas(self, net_param_deltas):
    assert self.pid == os.getpid()
    for p in net_param_deltas:
      self.net_train_param_deltas[p].set_value(net_param_deltas[p], borrow=True)

  def norm_constraint(self, tensor_var, max_norm, norm_axes=None, epsilon=1e-12):
    ndim = tensor_var.ndim

    if norm_axes is not None:
        sum_over = tuple(norm_axes)
    elif ndim == 2:  # DenseLayer
        sum_over = (0,)
    elif ndim == 3:  # Depth
        sum_over = (0,2)
    else:
        sum_over = (0,)

    dtype = numpy.dtype(theano.config.floatX).type
    norms = T.sqrt(T.sum(T.sqr(tensor_var), axis=sum_over, keepdims=True))
    target_norms = T.clip(norms, 0, dtype(max_norm))
    constrained_output = \
        (tensor_var * (target_norms / (dtype(epsilon) + norms)))

    return constrained_output

  def var(self, value, name="", broadcastable=None, reset=False, dtype="float32", zero=False):
    if zero:
      if isinstance(value, theano.compile.SharedVariable):
        value = value.get_value(borrow=True, return_internal_type=True)
      shape = value.shape
      value = numpy.zeros(shape, dtype=dtype)
    else:
      if isinstance(value, theano.compile.SharedVariable):
        value = value.get_value()
      value = numpy.asarray(value).astype(dtype)
    kwargs = {"value": value}
    if name: kwargs["name"] = name
    if broadcastable: kwargs["broadcastable"] = broadcastable
    param = theano.shared(**kwargs)
    if reset:
      self.params[param] = value
    return param

  def reset(self):
    #self.i.set_value(numpy.float32(0))
    return # this needs to be done smarter
    for param in self.params:
      param.set_value(self.params[param])

  def getUpdateList(self):
    assert self.pid == os.getpid()
    updates = []
    " :type: list[(theano.SharedVariable, theano.Variable)] "
    upd = { p: 0 for p in self.net_train_param_deltas.keys() }
    eps = 1e-7
    if self.adasecant:
      grads = OrderedDict({p: self.net_train_param_deltas[p] / (self.net_train_param_deltas[p].norm(2) + eps) for p in self.net_train_param_deltas.keys()})
      #grads = OrderedDict({p: self.net_train_param_deltas[target][p] for p in self.net_train_param_deltas[target].keys()})
      step = self.var(0, "adasecant_step")
    else:
      grads = self.net_train_param_deltas
    self.counter = self.var(0, name="counter", dtype="int64")
    updates.append((self.counter, self.counter + 1))
    i_t = self.i + 1.
    beta1=0.9
    beta2=0.999
    a_t = self.learning_rate_var * T.sqrt(1-beta2**i_t)/(1-beta1**i_t)
    for param in grads.keys():
      deltas = T.switch(T.or_(T.isinf(grads[param]), T.isnan(grads[param])), 0, grads[param])
      if self.max_norm > 0:
        deltas = self.norm_constraint(deltas, self.max_norm)
      #print param, param.get_value().shape, numpy.prod(param.get_value().shape)
      if self.gradient_clip > 0:
        # Note that there is also theano.gradient.grad_clip, which would clip it already
        # at the backprop step and which would affect also other dependent gradients.
        # However, this is simpler for now.
        # Also note that this is yet without the learning rate factor -
        # this might be different to other gradient clipping implementations.
        deltas = T.clip(deltas, -self.gradient_clip, self.gradient_clip)
      #if self.momentum > 0:
      #  upd[p] += self.momentum * self.deltas[param]
      if self.adasecant:
        # https://github.com/caglar/adasecant_wshp_paper/blob/master/adasecant/codes/learning_rule.py
        self.use_adagrad = False
        self.use_adadelta = False #True #True
        self.skip_nan_inf = False
        self.start_var_reduction = 0
        self.use_corrected_grad = True  #True
        self.decay = 0.95
        ### default
        self.delta_clip = 50.0
        self.outlier_detection = True
        self.gamma_clip = 1.8
        ### aggressive
        #self.delta_clip = None
        #self.outlier_detection = False
        #self.gamma_clip = None
        ### conservative
        #self.delta_clip = 50.0 #None
        #self.outlier_detection = True #False
        #self.gamma_clip = 1.8 #None #1.8

        #if self.skip_nan_inf:
          #If norm of the gradients of a parameter is inf or nan don't update that parameter
          #That might be useful for RNNs.
          #grads[param] = T.switch(T.or_(T.isinf(grads[param]), T.isnan(grads[param])), 0, grads[param])

        #grads[param] = T.unbroadcast(grads[param], -1)

        #print param, param.get_value().shape, numpy.prod(param.get_value().shape)

        #grads[param].name = "grad_%s" % param.name
        mean_grad = self.var(param.get_value() * 0. + eps, name="mean_grad_%s" % param.name, broadcastable=param.broadcastable)
        slow_constant = 2.1
        #mean_corrected_grad = self.var(param.get_value() * 0 + eps, name="mean_corrected_grad_%s" % param.name)
        if self.use_adagrad:
          # sum_square_grad := \sum_i g_i^2
          sum_square_grad = self.var(param.get_value(borrow=True) * 0., name="sum_square_grad_%s" % param.name, broadcastable=param.broadcastable)
        if self.use_adadelta:
          eg2 = self.var(param.get_value(borrow=True) * 0., name= "eg2_%s" % param.name, broadcastable=param.broadcastable)
          edx2 = self.var(param.get_value(borrow=True) * 0., name= "edx2_%s" % param.name, broadcastable=param.broadcastable)
          #dx = self.var(param.get_value(borrow=True) * 0., name= "dx_%s" % param.name)
        taus_x_t = self.var((numpy.ones_like(param.get_value()) + eps) * slow_constant,
                           name="taus_x_t_" + param.name, broadcastable=param.broadcastable)
        self.taus_x_t = taus_x_t

        #Variance reduction parameters
        #Numerator of the gamma:
        gamma_nume_sqr = self.var(numpy.zeros_like(param.get_value()) + eps,
                                  name="gamma_nume_sqr_" + param.name, broadcastable=param.broadcastable)

        #Denominator of the gamma:
        gamma_deno_sqr = self.var(numpy.zeros_like(param.get_value()) + eps,
                                  name="gamma_deno_sqr_" + param.name, broadcastable=param.broadcastable)

        #For the covariance parameter := E[\gamma \alpha]_{t-1}
        cov_num_t = self.var(numpy.zeros_like(param.get_value()) + eps,
                             name="cov_num_t_" + param.name, broadcastable=param.broadcastable)

        # mean_squared_grad := E[g^2]_{t-1}
        mean_square_grad = self.var(numpy.zeros_like(param.get_value()) + eps,
                                    name="msg_" + param.name, broadcastable=param.broadcastable)

        # mean_square_dx := E[(\Delta x)^2]_{t-1}
        mean_square_dx = self.var(value = param.get_value() * 0., name="msd_" + param.name, broadcastable=param.broadcastable)
        if self.use_corrected_grad:
            old_grad = self.var(value = param.get_value() * 0. + eps, name="old_grad_" + param.name, broadcastable=param.broadcastable)

        #The uncorrected gradient of previous of the previous update:
        old_plain_grad = self.var(param.get_value() * 0 + eps, broadcastable=param.broadcastable, name="old_plain_grad_" + param.name)
        mean_curvature = self.var(param.get_value() * 0 + eps, broadcastable=param.broadcastable, name="mean_curvature_" + param.name)
        mean_curvature_sqr = self.var(param.get_value() * 0 + eps, broadcastable=param.broadcastable, name="mean_curvature_sqr_" + param.name)

        # Initialize the E[\Delta]_{t-1}
        mean_dx = self.var(param.get_value() * 0., broadcastable=param.broadcastable, name="mean_dx_" + param.name)

        # Block-wise normalize the gradient:
        norm_grad = deltas #grads[param]

        #For the first time-step, assume that delta_x_t := norm_grad
        cond = T.eq(step, 0)
        msdx = cond * norm_grad**2 + (1 - cond) * mean_square_dx
        mdx = cond * norm_grad + (1 - cond) * mean_dx

        """
        Compute the new updated values.
        """
        # E[g_i^2]_t
        new_mean_squared_grad = (
            mean_square_grad * (self.decay)  +
            T.sqr(norm_grad) * (1 - self.decay)
        )
        new_mean_squared_grad.name = "msg_" + param.name
        # E[g_i]_t
        new_mean_grad = (
            mean_grad * (self.decay) +
            norm_grad * (1 - self.decay)
        )
        new_mean_grad.name = "nmg_" + param.name

        mg = new_mean_grad
        mgsq = new_mean_squared_grad

        # Keep the rms for numerator and denominator of gamma.
        new_gamma_nume_sqr = (
            gamma_nume_sqr * (1 - 1 / taus_x_t) +
            T.sqr((norm_grad - old_grad) * (old_grad - mg)) / taus_x_t
        )
        new_gamma_nume_sqr.name = "ngammasqr_num_" + param.name

        new_gamma_deno_sqr = (
            gamma_deno_sqr * (1 - 1 / taus_x_t) +
            T.sqr((mg - norm_grad) * (old_grad - mg)) / taus_x_t
        )
        new_gamma_deno_sqr.name = "ngammasqr_den_" + param.name

        gamma = T.sqrt(gamma_nume_sqr) / T.sqrt(gamma_deno_sqr + eps)
        gamma.name = "gamma_" + param.name

        if self.gamma_clip:
            gamma = T.minimum(gamma, self.gamma_clip)

        momentum_step = gamma * mg
        corrected_grad_cand = (norm_grad + momentum_step) / (1 + gamma)

        #For starting the variance reduction.
        if self.start_var_reduction > -1:
            cond = T.le(self.start_var_reduction, step)
            corrected_grad = cond * corrected_grad_cand + (1 - cond) * norm_grad
        else:
            corrected_grad = norm_grad

        if self.use_adagrad:
          g = corrected_grad
          # Accumulate gradient (windowed version)
          new_sum_squared_grad = (
              sum_square_grad + T.sqr(g)
          )

          rms_g_t = T.sqrt(new_sum_squared_grad)
          rms_g_t = T.maximum(rms_g_t, 1.0)
        if self.use_adadelta:
          decay = self.decay #self.adadelta_decay
          offset = eps #self.adadelta_offset
          g2 = T.sqr(corrected_grad)
          eg2_new = decay * eg2 + (1 - decay) * g2
          rms_g_t = T.sqrt(eg2_new + offset) / T.sqrt(edx2 + offset) #- 1.0 / dx_new
          #rms_g_t = T.maximum(rms_g_t, 1.0)

        # Use the gradients from the previous update
        # to compute the \nabla f(x_t) - \nabla f(x_{t-1})
        cur_curvature = norm_grad - old_plain_grad
        cur_curvature_sqr = T.sqr(cur_curvature)

        new_curvature_ave = (
            mean_curvature * (1 - 1 / taus_x_t) +
            (cur_curvature / taus_x_t)
        )
        new_curvature_ave.name = "ncurve_ave_" + param.name

        #Average average curvature
        nc_ave = new_curvature_ave

        new_curvature_sqr_ave = (
            mean_curvature_sqr * (1 - 1 / taus_x_t) +
            (cur_curvature_sqr / taus_x_t)
        )
        new_curvature_sqr_ave.name = "ncurve_sqr_ave_" + param.name

        #Unbiased average squared curvature
        nc_sq_ave = new_curvature_sqr_ave

        epsilon = self.learning_rate_var #lr_scalers.get(param, 1.) * self.learning_rate_var
        scaled_lr = 1.0 #self.var(1) #lr_scalers.get(param, 1.) * theano.shared(1.0, dtype = theano.config.floatX)
        rms_dx_tm1 = T.sqrt(msdx + epsilon)

        rms_curve_t = T.sqrt(new_curvature_sqr_ave + epsilon)

        #This is where the update step is being defined
        #delta_x_t = -scaled_lr * (rms_dx_tm1 / rms_curve_t - cov_num_t / (new_curvature_sqr_ave + epsilon))
        delta_x_t = -scaled_lr * (rms_dx_tm1 / rms_curve_t - cov_num_t / (new_curvature_sqr_ave + epsilon))
        delta_x_t.name = "delta_x_t_" + param.name

        # This part seems to be necessary for only RNNs
        # For feedforward networks this does not seem to be important.
        if self.delta_clip:
            #logger.info("Clipping will be applied on the adaptive step size.")
            delta_x_t = delta_x_t.clip(-self.delta_clip, self.delta_clip)
            if self.use_adagrad or self.use_adadelta:
                delta_x_t = delta_x_t * corrected_grad / rms_g_t
            else:
                #logger.info("Clipped adagrad is disabled.")
                delta_x_t = delta_x_t * corrected_grad
        else:
            #logger.info("Clipping will not be applied on the adaptive step size.")
            if self.use_adagrad or self.use_adadelta:
                delta_x_t = delta_x_t * corrected_grad / rms_g_t
            else:
                #logger.info("Clipped adagrad will not be used.")
                delta_x_t = delta_x_t * corrected_grad

        new_taus_t = (1 - T.sqr(mdx) / (msdx + eps)) * taus_x_t + self.var(1 + eps, name="stabilized")

        #To compute the E[\Delta^2]_t
        new_mean_square_dx = (
             msdx * (1 - 1 / taus_x_t) +
             (T.sqr(delta_x_t) / taus_x_t)
         )

        #To compute the E[\Delta]_t
        new_mean_dx = (
            mean_dx * (1 - 1 / taus_x_t) +
            (delta_x_t / (taus_x_t))
        )

        if self.outlier_detection:
          #Perform the outlier detection:
          #This outlier detection is slightly different:
          self.upper_bound_tau = 1e8
          self.lower_bound_tau = 1.5
          new_taus_t = T.switch(T.or_(abs(norm_grad - mg) > (2 * T.sqrt(mgsq  - mg**2)),
                                      abs(cur_curvature - nc_ave) > (2 * T.sqrt(nc_sq_ave - nc_ave**2))),
                                      self.var(2.2), new_taus_t)

          #Apply the bound constraints on tau:
          new_taus_t = T.maximum(self.lower_bound_tau, new_taus_t)
          new_taus_t = T.minimum(self.upper_bound_tau, new_taus_t)
        else:
          new_taus_t = new_taus_t

        new_cov_num_t = (
            cov_num_t * (1 - 1 / taus_x_t) +
            (delta_x_t * cur_curvature) * (1 / taus_x_t)
        )

        upd[param] = delta_x_t
        #upd[param] = - self.learning_rate_var * deltas

        # Apply updates
        updates.append((mean_square_grad, new_mean_squared_grad))
        updates.append((mean_square_dx, new_mean_square_dx))
        updates.append((mean_dx, new_mean_dx))
        updates.append((gamma_nume_sqr, new_gamma_nume_sqr))
        updates.append((gamma_deno_sqr, new_gamma_deno_sqr))
        updates.append((taus_x_t, new_taus_t))
        updates.append((cov_num_t, new_cov_num_t))
        updates.append((mean_grad, new_mean_grad))
        updates.append((old_plain_grad, norm_grad))
        updates.append((mean_curvature, new_curvature_ave))
        updates.append((mean_curvature_sqr, new_curvature_sqr_ave))
        #updates.append((param, param + update_step))

        if self.use_adagrad:
          updates.append((sum_square_grad, new_sum_squared_grad))
        if self.use_adadelta:
          edx2_new = self.decay * edx2 + (1 - self.decay) * delta_x_t ** 2
          updates.append((eg2, eg2_new))
          updates.append((edx2, edx2_new))
          #updates.append((dx, dx_new))

        if self.use_corrected_grad:
          updates.append((old_grad, corrected_grad))

      elif self.adam:
        value = param.get_value(borrow=True)
        epsilon=1e-8
        m_prev = theano.shared(numpy.zeros(value.shape, dtype=value.dtype),
                               broadcastable=param.broadcastable)
        v_prev = theano.shared(numpy.zeros(value.shape, dtype=value.dtype),
                               broadcastable=param.broadcastable)

        m_t = beta1*m_prev + (1-beta1)*deltas
        v_t = beta2*v_prev + (1-beta2)*deltas**2
        step = a_t*m_t/(T.sqrt(v_t) + epsilon)

        updates.append((m_prev, m_t))
        updates.append((v_prev, v_t))
        #updates.append((param, param - step))
        upd[param] += -step

      elif self.adagrad:
        epsilon = 1e-6
        accu_new = self.accu[param] + deltas ** 2
        updates.append((self.accu[param], accu_new))
        upd[param] += -self.learning_rate_var * deltas / T.sqrt(accu_new + epsilon)
        #updates.append((self.sqrsum[param], self.sqrsum[param] + deltas ** 2))
        #upd = upd * 0.1 / (0.1 + (self.sqrsum[param] + deltas ** 2) ** 0.5)
      elif self.adadelta:
        # http://arxiv.org/pdf/1212.5701v1.pdf
        decay = self.adadelta_decay
        offset = self.adadelta_offset
        g = deltas
        g2 = g ** 2
        eg2_new = decay * self.eg2[param] + (1 - decay) * g2
        dx_new = - g * T.sqrt(self.edx2[param] + offset) / T.sqrt(eg2_new + offset)
        edx2_new = decay * self.edx2[param] + (1 - decay) * dx_new ** 2
        updates.append((self.eg2[param], eg2_new))
        updates.append((self.edx2[param], edx2_new))
        updates.append((self.dx[param], dx_new))
        upd[param] += self.learning_rate_var * dx_new
      elif self.rmsprop:
        #https://github.com/Lasagne/Lasagne/blob/master/lasagne/updates.py#L398-L453
        accumulator = self.var(numpy.zeros(param.get_value(borrow=True, return_internal_type=True).shape,
                                       dtype=theano.config.floatX), broadcastable=param.broadcastable)
        epsilon=1e-6
        accumulator_new = self.rmsprop * accumulator + (1 - self.rmsprop) * deltas ** 2
        updates.append((accumulator, accumulator_new))
        upd[param] += - ((self.learning_rate_var * deltas)/T.sqrt(accumulator_new + epsilon))
      else:
        upd[param] += - self.learning_rate_var * deltas
      if self.momentum > 0:
        updates.append((self.deltas[param], upd[param]))
        upd[param] += self.deltas[param] * self.momentum
      if self.nesterov_momentum > 0:
        #The following code inspired by https://github.com/fidlej/optim/raw/master/dok/nesterov_simple.pdf
        velocity = self.var(numpy.zeros(param.get_value(borrow=True, return_internal_type=True).shape,
                                       dtype=theano.config.floatX), "velocity_%s" % param.name)
        tmp = self.nesterov_momentum * velocity + upd[param]
        updates.append((velocity, tmp))
        upd[param] += tmp*self.nesterov_momentum
      if self.momentum2 > 0:
        velocity = self.var(numpy.zeros(param.get_value(borrow=True, return_internal_type=True).shape,
                                       dtype=theano.config.floatX), "velocity_%s" % param.name)
        upd[param] += velocity * self.momentum2
        updates.append((velocity, upd[param]))

    # Simulate multi GPU training. This might help for regularization.
    if self.update_multiple_models:
      if not self.update_multiple_models_average_step:
        self.update_multiple_models_average_step = self.update_multiple_models
      cur_model = self.counter % self.update_multiple_models

      for param in grads.keys():
        models = [param]
        for i in range(self.update_multiple_models - 1):
          models += [self.var(param, name="%s_model_%i" % (param.name, i))]

        models_new = []
        for i, model_param in enumerate(models):
          is_cur_model = T.switch(T.eq(cur_model, i), numpy.float32(1), numpy.float32(0))
          models_new += [model_param + upd[param] * is_cur_model]

        is_cur_average_step = T.eq(self.counter % self.update_multiple_models_average_step, 0)
        average_new_model = reduce(T.add, models_new[1:], models_new[0]) / numpy.float32(self.update_multiple_models)
        for i in range(len(models)):
          models_new[i] = T.switch(is_cur_average_step, average_new_model, models_new[i])

        updates.extend(zip(models, models_new))

      upd.clear()

    #if upd:
      #updates.append((param, self.norm_constraint(param + upd, 1.0)))
      #updates.append((param, param + upd))
    updates.extend([(p, p + upd[p]) for p in upd if upd[p]])
    updates.append((self.i, i_t))
    if self.adasecant:
      updates.append((step, step + 1))
    #for u in updates:
    #  print ">>>>", u
    return updates

  def setLearningRate(self, learning_rate):
    """
    :type learning_rate: float
    """
    assert self.pid == os.getpid()
    self.learning_rate_var.set_value(learning_rate)

  def update(self):
    assert self.pid == os.getpid()
    updates = self.getUpdateList()
    updater = theano.function(inputs=[], updates=updates, name="updater")
    return updater()
