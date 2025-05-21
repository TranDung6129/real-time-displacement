import numpy as np
from scipy.signal import windows
from typing import Tuple, Optional

def calculate_fft(data_array: np.ndarray, 
                 dt: float,
                 n_fft_points: int,
                 window_type: str = 'Hann') -> Tuple[np.ndarray, np.ndarray]:
    """
    Calculate FFT of a data array with specified window function.
    
    Args:
        data_array: Input data array
        dt: Sampling time interval
        n_fft_points: Number of points for FFT
        window_type: Type of window function ('Hann', 'Hamming', 'Blackman', 'Rectangular')
        
    Returns:
        Tuple of (frequency array, amplitude spectrum)
    """
    if data_array.size < n_fft_points:
        return np.array([]), np.array([])
        
    # Get the last n_fft_points samples
    segment = data_array[-n_fft_points:]
    
    # Apply window function
    if window_type == 'Hann':
        window = windows.hann(n_fft_points)
    elif window_type == 'Hamming':
        window = windows.hamming(n_fft_points)
    elif window_type == 'Blackman':
        window = windows.blackman(n_fft_points)
    else:  # Rectangular
        window = np.ones(n_fft_points)
        
    segment_windowed = segment * window
    
    # Calculate FFT
    yf = np.fft.rfft(segment_windowed)
    xf = np.fft.rfftfreq(n_fft_points, dt)
    
    # Calculate amplitude spectrum
    amplitude_spectrum = np.abs(yf)
    
    return xf, amplitude_spectrum

def find_dominant_frequency(freq_array: np.ndarray,
                          amplitude_spectrum: np.ndarray,
                          min_freq: float = 0.1) -> Optional[float]:
    """
    Find the dominant frequency in the spectrum.
    
    Args:
        freq_array: Array of frequencies
        amplitude_spectrum: Array of amplitudes
        min_freq: Minimum frequency to consider
        
    Returns:
        Dominant frequency or None if not found
    """
    if freq_array.size == 0 or amplitude_spectrum.size == 0:
        return None
        
    # Find indices where frequency is above minimum
    min_freq_idx = np.where(freq_array >= min_freq)[0]
    if min_freq_idx.size == 0:
        return None
        
    # Find peak in amplitude spectrum
    start_idx = min_freq_idx[0]
    if start_idx >= len(amplitude_spectrum):
        return None
        
    peak_idx = np.argmax(amplitude_spectrum[start_idx:]) + start_idx
    return freq_array[peak_idx] 