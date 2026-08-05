Found It

Find things in your room, on your computer, and on your Android devices.

Found It is an experimental desktop search app that brings physical-object tracking and semantic file search into a single interface. It can watch a room through one or more cameras, detect and remember where objects were last seen, search local files by what they contain, and index files from an Android device over ADB.

The project is built in Python with PyQt5 and uses local machine-learning models for detection and semantic search.

What it can do

Room Tracker

Connect cameras and turn them into a searchable map of a physical room.

Detect common objects in live camera feeds with YOLOv8.

Track the last known position of detected items.

Map detections into configurable room zones.

Search for previously detected objects by name.

Keep snapshots and detection history locally.

Configure multiple rooms, cameras, zones, and drawers.

Support standard cameras, fisheye calibration, and 360°/equirectangular dewarping.

File Search

Search your computer using natural-language descriptions instead of exact filenames.

Index images, text files, source code, and other common supported formats.

Search images semantically with OpenCLIP.

Search text and code with sentence-transformer embeddings.

Match exact or partial filenames alongside semantic results.

Add an individual image under a custom name such as Passport for quick retrieval later.

Open a matching file or its containing folder directly from the app.

Example searches:

vacation photo with mountains
python file that handles database storage
notes about the server migration
red car at night

Other Devices

Found It can also index compatible files from an Android device using Android Debug Bridge.

Detect connected ADB devices.

Scan device storage over USB.

Semantically index images, text, and source files.

Search the device from the same style of interface as local file search.

Save known devices for easier reconnecting.

Tech stack

Component

Technology

Desktop UI

PyQt5

Object detection

Ultralytics YOLOv8

Computer vision

OpenCV

Image search

OpenCLIP / CLIP RN50

Text search

Sentence Transformers (all-MiniLM-L6-v2)

ML runtime

PyTorch

Local data

SQLite + JSON

Android access

ADB

Requirements

Python 3.10+ recommended

A webcam, USB camera, or other OpenCV-compatible camera for Room Tracker

Enough RAM/storage to load the ML models used by the enabled search modes

Android Platform Tools / adb only if you want to use Other Devices

The interface is currently developed primarily with Windows in mind, although much of the code is cross-platform.

Installation

Clone the repository and create a virtual environment:

git clone <repository-url>
cd Found-it
python -m venv .venv

Activate it on Windows:

.venv\Scripts\activate

Or on macOS/Linux:

source .venv/bin/activate

Install the dependencies:

pip install -r requirements.txt

Then launch Found It from the repository root:

python -m found_it.main

[!NOTE]The first launch or first use of a search feature may download model weights such as yolov8n.pt, OpenCLIP weights, or the sentence-transformer model. This can take longer than later launches.

Getting started

Track objects in a room

Open Room Setup.

Set the room dimensions.

Add and position your cameras.

Draw zones for areas such as a desk, shelf, closet, or drawer.

Save the room configuration.

Open Room Tracker to view detections and search for items.

Found It stores the last known location and snapshot of detected objects so you can search for them later.

Search files on your computer

Open File Search.

Add one or more folders.

Click Scan and let the app build embeddings for supported files.

Describe what you are trying to find in the search box.

Search is based on both filenames and semantic similarity, so a file does not need to contain the exact words in your query to appear as a result.

Search an Android device

Install Android Platform Tools and make sure adb is available on your system.

On the Android device, enable Developer Options and USB debugging, connect it over USB, and accept the debugging authorization prompt. Then:

Open Other Devices.

Click Connect.

Click Scan Device.

Search the indexed files with a natural-language description.

Supported file types

Local search currently recognizes common image formats such as JPEG, PNG, GIF, BMP, WebP, and TIFF; text/config formats such as TXT, Markdown, CSV, JSON, YAML, TOML, HTML, and logs; and many common programming-language extensions including Python, JavaScript, TypeScript, C/C++, C#, Go, Rust, Java, Swift, Kotlin, SQL, shell scripts, and more.

Project structure

found_it/
├── camera/       # Camera capture and fisheye/360 dewarping
├── detection/    # YOLO detection and room-coordinate mapping
├── device/       # ADB device discovery, scanning, and search
├── fileindex/    # Local file scanning, embeddings, and semantic search
├── gui/          # PyQt5 application interface
├── storage/      # SQLite database and data models
├── utils/        # Settings, room profiles, and saved-device helpers
├── config.py     # Default application configuration
└── main.py       # Application entry point

Runtime data is stored under data/, including the object database, snapshots, calibration data, room profiles, and app settings. Generated runtime data and downloaded model files are excluded from Git by the repository's .gitignore.

Configuration

Default values live in found_it/config.py.

Notable settings include:

CAMERA_RESOLUTION = (640, 480)
CAMERA_FPS = 15

YOLO_MODEL = "yolov8n.pt"
DETECTION_CONFIDENCE = 0.4
DETECTION_FRAME_SKIP = 3

ITEM_INACTIVE_SECONDS = 300
DEWARP_ENABLED = False
FISHEYE_FOV = 180.0

Camera detection confidence, frame skipping, room selection, and related settings can also be changed through the application UI.

Current limitations

Found It is still an experimental project, so several parts of the workflow are intentionally simple.

Semantic file and Android-device embeddings are kept in memory and are rebuilt after the app restarts.

Object recognition is limited to classes known by the configured YOLO model unless a different model is supplied.

Physical positions are estimates derived from camera detections and room configuration, not precision spatial tracking.

Large folders or devices can take significant time and memory to index.

Android search requires ADB access and USB debugging.

There is not yet a packaged installer or release build in this repository.

Privacy

Found It performs detection, indexing, and search locally. Room history, snapshots, settings, and saved-device information are stored on the machine running the application. ML libraries may download model weights from their respective model providers when a model is used for the first time.

License

Found It is licensed under the MIT License.
