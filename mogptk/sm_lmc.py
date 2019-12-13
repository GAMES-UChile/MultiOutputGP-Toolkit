from .model import model
from .kernels import SpectralMixtureLMC, Noise

class SM_LMC(model):
    """
    Spectral Mixture - Linear Model of Coregionalization kernel with Q components and Rq latent functions.
        
    Args:
        dataset (mogptk.DataSet): DataSet object of data for all channels.
        Q (int): Number of components to use.
        Rq (int): Number of subcomponents to use.
        name (string): Name of the model.
        likelihood (gpflow.likelihoods): Likelihood to use from GPFlow, if None a default exact inference Gaussian likelihood is used.
        variational (bool): If True, use variational inference to approximate function values as Gaussian. If False it will use Monte Carlo Markov Chain (default).
        sparse (bool): If True, will use sparse GP regression. Defaults to False.
        like_params (dict): Parameters to GPflow likelihood.
    """
    def __init__(self, dataset, Q=1, Rq=1, name="SM-LMC", likelihood=None, variational=False, sparse=False, like_params={}):
        if Rq != 1:
            raise Exception("Rq != 1 is not (yet) supported") # TODO: support

        model.__init__(self, name, dataset)
        self.Q = Q
        self.Rq = Rq

        with self.graph.as_default():
            with self.session.as_default():
                for q in range(self.Q):
                    kernel = SpectralMixtureLMC(
                        self.dataset.get_input_dims()[0],
                        self.dataset.get_output_dims(),
                        self.Rq,
                    )
                    if q == 0:
                        kernel_set = kernel
                    else:
                        kernel_set += kernel
                kernel_set += Noise(self.dataset.get_input_dims()[0], self.dataset.get_output_dims())
                self._build(kernel_set, likelihood, variational, sparse, like_params)
    
    def estimate_params(self, method='BNSE', sm_init='BNSE', sm_method='BFGS', sm_maxiter=2000, plot=False):
        """
        Estimate kernel parameters.

        The initialization can be done in two ways, the first by estimating the PSD via 
        BNSE (Tobar 2018) and then selecting the greater Q peaks in the estimated spectrum,
        the peaks position, magnitude and width initialize the mean, magnitude and variance
        of the kernel respectively.
        The second way is by fitting independent Gaussian process for each channel, each one
        with SM kernel, using the fitted parameters for initial values of the multioutput kernel.

        In all cases the noise is initialized with 1/30 of the variance 
        of each channel.

        Args:
            mode (str): Method of initializing, possible values are 'BNSE' and SM.
            sm_init (str): Method of initializing SM kernels. Only valid in 'SM' mode.
            sm_method (str): Optimization method for SM kernels. Only valid in 'SM' mode.
            sm_maxiter (str): Maximum iteration for SM kernels. Only valid in 'SM' mode.
            plt (bool): Show the PSD of the kernel after fitting SM kernels.
                Only valid in 'SM' mode. Default to false.
        """
        
        if method == 'BNSE':
            amplitudes, means, variances = self.dataset.get_bnse_estimation(self.Q)
            for q in range(self.Q):
                constant = np.empty((self.dataset.get_input_dims()[0], self.dataset.get_output_dims()))
                for channel in range(len(self.dataset)):
                    constant[:, channel] = amplitudes[channel, :, q].mean()
            
                constant = np.sqrt(constant / constant.mean())
                mean = means[:, :, q].mean(axis=0)
                variance = variances[:, :, q].mean(axis=0)

                self.set_param(q, 'constant', constant)
                self.set_param(q, 'mean', mean * 2 * np.pi)
                self.set_param(q, 'scale', variance * 2)
        elif method == 'SM':
            params = _estimate_from_sm(self.dataset, self.Q, init=sm_init, method=sm_method, maxiter=sm_maxiter, plot=plot)
            for q in range(self.Q):
                self.set_param(q, 'constant', params[q]['weight'].mean(axis=0).reshape(self.Rq, -1))
                self.set_param(q, 'mean', params[q]['mean'].mean(axis=1))
                self.set_param(q, 'variance', params[q]['scale'].mean(axis=1) * 2)
        else:
            raise Exception("possible modes are either 'BNSE' or 'SM'")

        noise = np.empty((self.dataset.get_output_dims()))
        for i, channel in enumerate(self.dataset):
            noise[i] = (channel.Y).var() / 30
        self.set_param(self.Q, 'noise', noise)
