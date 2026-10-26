# AttendEase – Face Recognition Attendance Management System

**AttendEase** is a web-based attendance management system that uses face recognition to help automate student attendance and simplify attendance record management.

## Features

- **Admin Dashboard:** Manage the attendance system through an admin interface.
- **Student Management:** Register and manage student information.
- **Face Registration:** Register student and faculty face data.
- **Face Recognition:** Recognize registered faces using InsightFace.
- **Automatic Attendance:** Mark recognized students as present and automatically approve successful matches.
- **Faculty Verification:** Require faculty face verification before accessing attendance records.
- **Attendance Reports:** View and manage attendance records.

## Tech Stack

- **Language:** Python
- **Backend:** Flask
- **Database:** SQLite
- **Face Recognition:** InsightFace
- **Image Processing:** OpenCV, NumPy
- **Frontend:** HTML, CSS, JavaScript
- **Testing:** pytest

## How It Works

1. The admin logs in and manages students, faculty, and class sessions.
2. Registered face data is used to recognize students during attendance.
3. Confident matches can be automatically marked as present.
4. Faculty members verify their identity using their registered face before accessing assigned-class attendance records.
5. Attendance records can be reviewed and managed through the application.

## Installation and Setup

For complete installation instructions, database migration steps, environment configuration, and webcam testing, see [SETUP_AND_TESTING.md](SETUP_AND_TESTING.md).

## Documentation

- [Feature Changes](CHANGES_FACULTY_WEBCAM_REVIEW.md)
- [Test Results and Limitations](TEST_RESULTS.md)
- [Setup and Testing Guide](SETUP_AND_TESTING.md)

## Testing

The project documentation reports **106 passing automated tests**. These tests include faculty verification, automatic attendance approval, audit events, and database migration scenarios.

Real hardware webcam access, full model inference accuracy, and production deployment have not been verified.

## Security and Limitations

- Face verification is not the same as liveness detection or complete protection against spoofing.
- Recognition accuracy depends on the model, camera conditions, and validated thresholds.
- Use synthetic or authorized data when testing.
- Do not commit passwords, secret keys, private databases, or biometric images to GitHub.

## Author

**Sanjana**

*Educational project exploring backend development, database management, computer vision, and applied AI.*