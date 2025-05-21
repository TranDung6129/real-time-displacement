import numpy as np
from typing import Dict, List, Tuple, Union, Optional

def calculate_descriptive_stats(data_dict: Dict[str, np.ndarray]) -> List[Dict[str, Union[str, float]]]:
    """
    Calculate descriptive statistics for multiple data arrays.
    
    Args:
        data_dict: Dictionary of data arrays with field names as keys
        
    Returns:
        List of dictionaries containing statistics for each metric
    """
    metrics = ["Mean", "Median", "Std Dev", "Min", "Max", "Variance"]
    stats_list = []
    
    for metric_name in metrics:
        row_data = {'Metric': metric_name}
        for field, data_array in data_dict.items():
            if data_array.size == 0:
                row_data[field] = "N/A"
                continue
                
            if metric_name == "Mean": row_data[field] = np.mean(data_array)
            elif metric_name == "Median": row_data[field] = np.median(data_array)
            elif metric_name == "Std Dev": row_data[field] = np.std(data_array)
            elif metric_name == "Min": row_data[field] = np.min(data_array)
            elif metric_name == "Max": row_data[field] = np.max(data_array)
            elif metric_name == "Variance": row_data[field] = np.var(data_array)
            
        stats_list.append(row_data)
    
    return stats_list

def calculate_correlation_matrix(data_dict: Dict[str, np.ndarray]) -> Tuple[np.ndarray, List[str]]:
    """
    Calculate correlation matrix for multiple data arrays.
    
    Args:
        data_dict: Dictionary of data arrays with field names as keys
        
    Returns:
        Tuple of (correlation matrix, field names)
    """
    field_names = list(data_dict.keys())
    data_matrix = np.array([data_dict[field] for field in field_names]).T
    corr_matrix = np.corrcoef(data_matrix, rowvar=False)
    return corr_matrix, field_names

def calculate_histogram(data_array: np.ndarray, num_bins: int = 50) -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculate histogram for a data array.
    
    Args:
        data_array: Input data array
        num_bins: Number of histogram bins
        
    Returns:
        Tuple of (histogram values, bin edges)
    """
    if data_array.size == 0:
        return np.array([]), np.array([])
        
    hist, bin_edges = np.histogram(data_array, bins=num_bins)
    return hist, bin_edges 