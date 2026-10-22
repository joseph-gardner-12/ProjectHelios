"""Explicit body-FRD, survey-ENU, and EKF-NED transforms."""

import numpy as np
from scipy.spatial.transform import Rotation


def body_to_enu(roll, pitch, yaw):
    ned = Rotation.from_euler("ZYX", [yaw, pitch, roll]).as_matrix()
    return np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]]) @ ned


def enu_to_ned(position, dock_in_ned):
    return np.array([position.y, position.x, -position.z]) + np.asarray(dock_in_ned)


def covariance_to_ned(covariance):
    transform = np.array([[0, 1, 0], [1, 0, 0], [0, 0, -1]])
    return transform @ np.asarray(covariance) @ transform.T
