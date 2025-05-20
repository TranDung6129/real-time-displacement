import numpy as np
import logging
from .rls_filter import RLSFilter
from .integrator import SignalIntegrator

logger = logging.getLogger(__name__)

class KinematicProcessor:
    """
    Processes acceleration data to calculate velocity and displacement in real-time.
    It uses numerical integration and RLS filtering to remove drift.
    This class replaces the original RealTimeAccelerationIntegrator.
    """
    def __init__(self, dt, sample_frame_size=20, calc_frame_multiplier=100,
                 rls_filter_q_vel=0.9825, rls_filter_q_disp=0.9825,
                 warmup_frames=5):
        """
        Initializes the KinematicProcessor.

        Args:
            dt (float): Time interval between acceleration samples (seconds).
            sample_frame_size (int): Number of samples in one processing frame.
            calc_frame_multiplier (int): Multiplier for the internal calculation buffer size
                                         relative to sample_frame_size.
            rls_filter_q_vel (float): Forgetting factor for the velocity RLS filter.
            rls_filter_q_disp (float): Forgetting factor for the displacement RLS filter.
            warmup_frames (int): Number of frames to process before results are considered reliable.
        """
        self.dt = dt
        self.sample_frame_size = sample_frame_size
        self.calc_frame_size = sample_frame_size * calc_frame_multiplier
        
        self.acc_buffer = np.zeros(self.calc_frame_size)
        self.vel_buffer_detrended = np.zeros(self.calc_frame_size)
        self.disp_buffer_detrended = np.zeros(self.calc_frame_size)

        self.integrator = SignalIntegrator(dt=self.dt)
        self.rls_filter_vel = RLSFilter(filter_q=rls_filter_q_vel)
        self.rls_filter_disp = RLSFilter(filter_q=rls_filter_q_disp)
        
        # Pre-calculate time vector for the buffer length
        self.time_vector_buffer = np.arange(0, self.calc_frame_size * self.dt, self.dt)[:self.calc_frame_size]

        self.frame_count = 0
        self.warmup_frames = warmup_frames
        
        logger.info(f"KinematicProcessor initialized: dt={dt}, frame_size={sample_frame_size}, "
                    f"calc_buffer_size={self.calc_frame_size}, "
                    f"q_vel={rls_filter_q_vel}, q_disp={rls_filter_q_disp}, warmup={warmup_frames}")

    def is_warmed_up(self):
        """Checks if the processor has processed enough frames for reliable output."""
        return self.frame_count >= self.warmup_frames

    def reset(self):
        """Resets the processor to its initial state."""
        self.acc_buffer.fill(0)
        self.vel_buffer_detrended.fill(0)
        self.disp_buffer_detrended.fill(0)
        
        self.rls_filter_vel.reset()
        self.rls_filter_disp.reset()
        
        self.frame_count = 0
        logger.info("KinematicProcessor reset.")

    def _process_full_buffer(self):
        """
        Internal method to integrate and detrend the entire current acc_buffer.
        RLS filters are stateful and update their state internally.
        """
        raw_vel_buffer = self.integrator.integrate(self.acc_buffer)
        self.vel_buffer_detrended, _ = self.rls_filter_vel.detrend(raw_vel_buffer, self.time_vector_buffer)
        
        raw_disp_buffer = self.integrator.integrate(self.vel_buffer_detrended)
        self.disp_buffer_detrended, _ = self.rls_filter_disp.detrend(raw_disp_buffer, self.time_vector_buffer)
        
        # Acceleration is not filtered in this scheme, passed through
        return self.disp_buffer_detrended, self.vel_buffer_detrended, self.acc_buffer

    def process_frame(self, acc_frame_new):
        """
        Processes a new frame of acceleration data.

        Args:
            acc_frame_new (np.ndarray): New frame of acceleration data.

        Returns:
            tuple: (disp_output, vel_output, acc_output) for the new frame.
        """
        frame_len = len(acc_frame_new)
        if frame_len == 0:
            logger.warning("Received empty acceleration frame. Using sample_frame_size for NaN output.")
            nan_output_len = self.sample_frame_size
            return (np.full(nan_output_len, np.nan),
                    np.full(nan_output_len, np.nan),
                    np.full(nan_output_len, np.nan))

        actual_frame_len_for_processing = self.sample_frame_size
        processed_acc_frame = np.zeros(self.sample_frame_size)

        if frame_len >= self.sample_frame_size:
            if frame_len > self.sample_frame_size:
                logger.warning(f"Input frame length ({frame_len}) > sample_frame_size ({self.sample_frame_size}). Truncating.")
            processed_acc_frame[:] = acc_frame_new[:self.sample_frame_size]
        else: # frame_len < self.sample_frame_size
            logger.warning(f"Input frame length ({frame_len}) < sample_frame_size ({self.sample_frame_size}). Padding with last value.")
            processed_acc_frame[:frame_len] = acc_frame_new
            if frame_len > 0:
                processed_acc_frame[frame_len:] = acc_frame_new[-1] # Pad with the last value
            else: # frame_len == 0 was handled, but defensive
                processed_acc_frame[frame_len:] = 0 # Pad with zeros if somehow frame_len is 0 here
        
        # The output length will be actual_frame_len_for_processing (i.e., sample_frame_size)
        output_segment_len = actual_frame_len_for_processing

        self.frame_count += 1
            
        self.acc_buffer = np.roll(self.acc_buffer, -output_segment_len)
        self.acc_buffer[-output_segment_len:] = processed_acc_frame
        
        disp_full, vel_full, acc_full_buffer = self._process_full_buffer()
            
        disp_output = disp_full[-output_segment_len:]
        vel_output = vel_full[-output_segment_len:]
        # Return the processed (truncated/padded) acceleration frame segment from the buffer
        acc_output = acc_full_buffer[-output_segment_len:] 

        if not self.is_warmed_up():
             logger.debug(f"Frame {self.frame_count}/{self.warmup_frames} processed (warm-up phase).")
        
        return disp_output, vel_output, acc_output

    def get_cumulative_results(self):
        """Returns the current full internal buffers and corresponding time vector."""
        return self.time_vector_buffer, self.disp_buffer_detrended, self.vel_buffer_detrended, self.acc_buffer 