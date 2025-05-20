import numpy as np
import logging

logger = logging.getLogger(__name__)

class RLSFilter:
    """
    Implements a Recursive Least Squares (RLS) filter to remove linear trends
    from a data series. The model is y = a*t + b.
    """
    def __init__(self, filter_q=0.98, initial_P_diag=1000):
        """
        Initializes the RLS filter.

        Args:
            filter_q (float): Forgetting factor (lambda). Values closer to 1
                              give more weight to past data (smoother, less responsive).
            initial_P_diag (float): Diagonal value for the initial covariance matrix P.
                                    Represents initial uncertainty in parameters.
        """
        if not (0 < filter_q <= 1):
            raise ValueError("Forgetting factor (filter_q) must be between 0 (exclusive) and 1 (inclusive).")
        self.filter_q = filter_q
        self.initial_P_diag = initial_P_diag
        # P: Covariance matrix, theta: [a, b] parameters for y = a*t + b
        self.P = np.eye(2) * self.initial_P_diag
        self.theta = np.zeros(2)
        logger.info(f"RLSFilter initialized with q={filter_q}, initial_P_diag={initial_P_diag}")

    def reset(self):
        """Resets the filter to its initial state."""
        self.P = np.eye(2) * self.initial_P_diag
        self.theta = np.zeros(2)
        logger.info("RLSFilter reset.")

    def detrend(self, data, time_vector):
        """
        Removes a linear trend from the data using the RLS algorithm.
        This method updates the filter's state with each call.

        Args:
            data (np.ndarray): The input data series.
            time_vector (np.ndarray): The corresponding time vector for the data.

        Returns:
            tuple: (detrended_data, trend)
                   - detrended_data (np.ndarray): Data with the linear trend removed.
                   - trend (np.ndarray): The calculated linear trend.
        """
        if len(data) != len(time_vector):
            raise ValueError("Data and time_vector must have the same length.")
        
        n = len(data)
        trend_values = np.zeros_like(data)
        
        for i in range(n):
            phi = np.array([time_vector[i], 1.0]) # Regressor vector for y = a*t + b
            
            y_pred = np.dot(self.theta, phi) # Predict using current parameters
            e = data[i] - y_pred # Prediction error
            
            # Update gain vector k
            P_phi = np.dot(self.P, phi)
            denom = self.filter_q + np.dot(phi, P_phi)
            k = P_phi / denom if denom != 0 else np.zeros_like(phi)
            
            # Update parameters theta
            self.theta = self.theta + k * e
            
            # Update covariance matrix P
            self.P = (self.P - np.outer(k, np.dot(phi, self.P))) / self.filter_q
        
        # Calculate the trend based on the final (updated) theta for this batch
        for i in range(n):
            trend_values[i] = np.dot(self.theta, np.array([time_vector[i], 1.0]))
            
        detrended_data = data - trend_values
        return detrended_data, trend_values 