import numpy as np
from typing import Tuple, List, Dict, Optional
from scipy import stats

def detect_outliers_zscore(data_array: np.ndarray, 
                          threshold: float = 3.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect outliers using Z-score method.
    
    Args:
        data_array: Input data array
        threshold: Z-score threshold for outlier detection
        
    Returns:
        Tuple of (outlier indices, outlier values)
    """
    if data_array.size == 0:
        return np.array([]), np.array([])
        
    z_scores = np.abs(stats.zscore(data_array))
    outlier_indices = np.where(z_scores > threshold)[0]
    outlier_values = data_array[outlier_indices]
    
    return outlier_indices, outlier_values

def detect_anomalies_moving_average(data_array: np.ndarray,
                                  window_size: int = 20,
                                  threshold: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect anomalies using moving average and standard deviation.
    
    Args:
        data_array: Input data array
        window_size: Size of moving window
        threshold: Number of standard deviations for anomaly detection
        
    Returns:
        Tuple of (anomaly indices, anomaly values)
    """
    if data_array.size < window_size:
        return np.array([]), np.array([])
        
    # Calculate moving average and standard deviation
    moving_avg = np.convolve(data_array, np.ones(window_size)/window_size, mode='valid')
    moving_std = np.array([np.std(data_array[i:i+window_size]) 
                          for i in range(len(data_array)-window_size+1)])
    
    # Calculate upper and lower bounds
    upper_bound = moving_avg + threshold * moving_std
    lower_bound = moving_avg - threshold * moving_std
    
    # Find anomalies
    anomalies = np.zeros_like(data_array, dtype=bool)
    anomalies[window_size-1:] = (data_array[window_size-1:] > upper_bound) | \
                               (data_array[window_size-1:] < lower_bound)
    
    anomaly_indices = np.where(anomalies)[0]
    anomaly_values = data_array[anomaly_indices]
    
    return anomaly_indices, anomaly_values

def detect_sudden_changes(data_array: np.ndarray,
                         threshold: float = 2.0) -> Tuple[np.ndarray, np.ndarray]:
    """
    Detect sudden changes in time series data.
    
    Args:
        data_array: Input data array
        threshold: Threshold for change detection
        
    Returns:
        Tuple of (change indices, change magnitudes)
    """
    if data_array.size < 2:
        return np.array([]), np.array([])
        
    # Calculate differences between consecutive points
    differences = np.diff(data_array)
    
    # Find points where difference exceeds threshold
    change_indices = np.where(np.abs(differences) > threshold)[0]
    change_magnitudes = differences[change_indices]
    
    return change_indices, change_magnitudes 