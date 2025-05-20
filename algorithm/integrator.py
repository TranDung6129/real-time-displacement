import numpy as np
import logging

logger = logging.getLogger(__name__)

class SignalIntegrator:
    """
    Performs numerical integration of a signal, typically using the
    cumulative trapezoidal rule.
    """
    def __init__(self, dt):
        """
        Initializes the SignalIntegrator.

        Args:
            dt (float): The time step (sampling interval) between data points.
        """
        if dt <= 0:
            raise ValueError("Time step dt must be positive.")
        self.dt = dt
        logger.info(f"SignalIntegrator initialized with dt={dt}")

    def integrate(self, data_series):
        """
        Integrates the input data series using the cumulative trapezoidal rule.
        The initial condition of the integrated series is assumed to be zero.

        Args:
            data_series (np.ndarray): The input data series to integrate (1D array).

        Returns:
            np.ndarray: The integrated data series.
        """
        if not isinstance(data_series, np.ndarray) or data_series.ndim != 1:
            raise ValueError("Input data_series must be a 1D numpy array.")
        if len(data_series) == 0:
            return np.array([])
        
        integrated_series = np.zeros_like(data_series, dtype=float)
        # Cumulative trapezoidal integration
        for i in range(1, len(data_series)):
            integrated_series[i] = integrated_series[i-1] + \
                                   (data_series[i-1] + data_series[i]) * self.dt / 2
        return integrated_series 