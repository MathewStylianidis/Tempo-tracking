""" Class definition for particle filter based tempo tracking """
import numpy as np

__author__ = "Matthaios Stylianidis"


class SwitchingKalmanFilterTracker:
    """ Switching Kalman Filter class from tempo tracking

    The switching variable is computed either with an "ideal computation" or by approximating its distribution
    through particle filtering.


    Attributes:
        timestamps (list): A list of the timestamps corresponding to the estimated states.
        estimated_states (list): List of estimated states.
        score_positions (list): A list of the score positions c_k, used to estimate the score difference.
        score_differences (list): A list of the score difference gamma_k = c_k - c_{k-1}.
        state (np.ndarray): Currently predicted state array containing two values - the next onset time and the
            current tempo estimate. Period is the time between two consecutive beats, not two consecutive notes.
        P (np.ndarraay): State estimate covariance.
        A (np.ndarray): Transition matrix to convert x_{k-1} to x_k, during the prediction stage.
        C (np.ndarray): Matrix for mapping the state variable to an observation.
        K (np.ndarray): The Kalman Gain term.
        use_ideal_switch_value (bool): If set to true the ideal switch variable value is used and particle filter-
                ing is not employed.
        switch_variable_values (np.ndarray): Numpy array with switch variable discrete possible values
        switch_variable_val_count (int): Number of discrete switch variable possible values
        SWITCH_VARIABLE_RESOLUTION (float): resolution if switch variable discrete values
        SWITCH_VARIABLE_MAX (float): Maximum continuous value of switch variable

    """
    SWITCH_VARIABLE_RESOLUTION = 0.25
    SWITCH_VARIABLE_MAX = 4.0

    def __init__(self,
                 init_tempo_period: float = 1.0,
                 init_state_covariance_std: float = 1.0,
                 onset_process_noise_std: float = 0.01,
                 tempo_process_noise_std: float = 0.01,
                 measurement_noise_std: float = 0.1,
                 use_ideal_switch_value: bool = False,
                 particle_no: int = 10):
        """
        Args:
             start_time (float): Starting time of the track
             init_tempo_period (float): Initial value of tempo period.
             onset_process_noise_std (float): Process standard deviation for onset time.
             tempo_process_noise_std (float): Process standard deviation for tempo.
             measurement_noise_std (float): Measurement model standard deviation.
             use_ideal_switch_value (bool): If set to true the ideal switch variable value is used and particle filter-
                ing is not employed.
             particle_no (int): Number of particles for estimating the switching variable.
        """
        self.timestamps = []
        self.estimated_states = []
        self.estimated_covs = []
        self.score_positions = []
        self.score_differences = []
        self.A = np.array([[1, 1], [0, 1]], dtype=np.float64)
        self.C = np.array([1, 0], dtype=np.float64).reshape((1, 2))
        self.state = np.array([0.0, init_tempo_period], dtype=np.float64).reshape((-1, 1))
        self.P = np.diag([init_state_covariance_std**2, init_state_covariance_std**2]).astype(dtype=np.float64)
        self.R = np.diag([onset_process_noise_std**2, tempo_process_noise_std**2]).astype(dtype=np.float64)
        self.Q = np.diag([measurement_noise_std**2]).astype(dtype=np.float64)
        self.K = self.P @ self.C.T @ np.linalg.inv(self.C @ self.P @ self.C.T + self.Q)
        self.use_ideal_switch_value = use_ideal_switch_value
        self.switch_variable_val_count = self.SWITCH_VARIABLE_MAX / self.SWITCH_VARIABLE_RESOLUTION
        self.switch_variable_values = np.array([(i + 1) * self.SWITCH_VARIABLE_RESOLUTION
                                                for i in range(int(self.switch_variable_val_count))], dtype=np.float64)
        # Initialize particle set
        if not self.use_ideal_switch_value:
            self.particle_no = particle_no
            self.particles = self.init_particles(self.particle_no)
            self.particle_weights = np.full((self.particle_no, 1), 1/self.particle_no)
            # Create as many replicas of the Kalman Filter variables as the number of particles
            self.state = np.tile(self.state, (self.particle_no, 1, 1))
            self.A = np.tile(self.A, (self.particle_no, 1, 1))
            self.A[:, 1, 1] = self.particles
            self.P = np.tile(self.P, (self.particle_no, 1, 1))
            self.K = np.tile(self.K.T, (self.particle_no, 1))[..., np.newaxis]

    def init_particles(self, particle_no):
        """ Initializes particle distribution """
        # Sample uniformly with replacement from the grid of possible score differences
        return np.random.choice(self.switch_variable_values, particle_no)

    def predict(self):
        if self.use_ideal_switch_value:
            self.state = self.A @ self.state
            self.P = self.A @ self.P @ self.A.T + self.R
        else:
            for i in range(self.particle_no):
                self.state[i] = self.A[i] @ self.state[i]
                self.P[i] = self.A[i] @ self.P[i] @ self.A[i].T + self.R

    def update(self, onset_time):
        """ Estimates state and state uncertainty given a new onset time observation. """
        if self.use_ideal_switch_value:
            self.state = self.state + self.K @ (onset_time - self.C @ self.state)
            self.P = self.P - self.K @ self.C @ self.P
            self.estimated_states.append(self.state)
            self.estimated_covs.append(self.P)
        else:
            for i in range(self.particle_no):
                self.state[i] = self.state[i] + self.K[i] @ (onset_time - self.C @ self.state[i])
                self.P[i] = self.P[i] - self.K[i] @ self.C @ self.P[i]
            # Assign particle with maximum probability to estimated states
            max_prob_particle = np.argmax(self.particle_weights)
            self.estimated_states.append(self.state[max_prob_particle])
            self.estimated_covs.append(self.P[max_prob_particle])

    def compute_kalman_gain(self):
        if self.use_ideal_switch_value:
            self.K = self.P @ self.C.T @ np.linalg.inv(self.C @ self.P @ self.C.T + self.Q)
        else:
            for i in range(self.particle_no):
                self.K[i] = self.P[i] @ self.C.T @ np.linalg.inv(self.C @ self.P[i] @ self.C.T + self.Q)

    def run(self, onset_time):
        if len(self.estimated_states) == 0:
            # Incorporate measurement into state estimation
            self.update(onset_time)
        else:
            # Update switch variable based on previously estimated state / Systematic resampling of particles
            self.update_switch_variable(onset_time)
            # Predict new states
            self.predict()
            # Update Kalman Gain
            self.compute_kalman_gain()
            # Incorporate measurement into state estimation
            self.update(onset_time)

    def get_estimates(self):
        return self.estimated_states

    def get_tempo_estimates(self):
        return np.array([x[1] for x in self.estimated_states], dtype=np.float64)

    def update_switch_variable(self, onset_time):
        """ Update switch value according to particle filtering

        According to the derivation in https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.217.32&rep=rep1&type=pdf
        the ideal switch variable value for which the residual e_k is zero can be calculated as follows:

        e_k (residual) = y_k - C x_pred_{k} = y_k - C A x_{k-1} =  0 => (y_k - r_{k-1}) / Delta_{k-1} = gamma_k

        where Delta is the tempo period, gamma is the score difference, and y_k is the observation (onset time).

        However, we use particle filtering to estimate and track the switch variable since it is a random discrete vari
        able.
        """
        if self.use_ideal_switch_value:
            last_est_onset, last_est_tempo = self.estimated_states[-1]
            ideal_score = (onset_time - last_est_onset) / last_est_tempo
            rounded_ideal_score = self.switch_variable_values[np.abs(ideal_score - self.switch_variable_values).argmin()]
            self.A[0, 1] = rounded_ideal_score
        else:
            covE = (self.C @ self.estimated_covs[-1] @ self.C.T + self.R)[0, 0]

            for i in range(self.particle_no):
                residual = onset_time - self.C @ self.state[i]
                self.particle_weights[i] = (1 / np.sqrt(covE * 2 * np.pi)) * np.exp(-0.5 * residual ** 2 * covE ** -1)

            # Normalize weights and perform systematic resampling
            self.particle_weights /= self.particle_weights.sum()
            self.systematic_resampling()

    def systematic_resampling(self):
        """ Systematic resampling for particles """
        # Calculate CDF of weights
        new_particle_set = np.zeros_like(self.particles)
        new_states = np.zeros_like(self.state)
        new_A = np.zeros_like(self.A)
        new_P = np.zeros_like(self.P)

        CDF = np.cumsum(self.particle_weights)
        r_0 = np.random.random()
        for m in range(self.particle_no):
            r = min(r_0 + (m - 1) / self.particle_no, 1.0)
            i = min(np.searchsorted(CDF, r), self.particle_no - 1)
            new_particle_set[m] = self.particles[i]
            new_states[m] = self.state[i]
            new_A[m] = self.A[i]
            new_P[m] = self.P[i]

        self.particles = new_particle_set
        self.A = new_A
        self.P = new_P
        self.state = new_states

    @staticmethod
    def tempo_period_to_bpm(period):
        return 60.0 / period
