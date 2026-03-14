# UI Module - Modular Frontend Architecture

This directory contains the NiceGUI-based web interface for the RPI Surveillance System.

## Module Overview

The frontend has been refactored into a modular architecture for better maintainability and extensibility.

### Core Modules

#### `web.py` - Application Orchestrator
- Main entry point for the web application
- Defines the root route (`/`) with tabbed navigation
- Integrates all other UI modules
- Contains `run_app()` function to start the server

**Key Functions:**
- `main_menu()` - Root page with tabs for Home, Live View, Recordings, Settings
- `run_app()` - Starts NiceGUI server on port 9000

#### `login.py` - Authentication System
- Handles user authentication and session management
- Protects routes with middleware

**Key Components:**
- `AuthMiddleware` - Redirects unauthenticated users to login
- `login_page()` - Login form UI at `/login`
- `logout()` - Clears session and redirects to login
- `setup_auth_middleware()` - Initializes auth middleware

**Default Credentials:**
- `user1` / `pass1`
- `user2` / `pass2`
- `admin` / `admin`

⚠️ **Security Note:** Change these credentials in production!

#### `live_view.py` - Real-time Surveillance
- Live camera streaming and control interface
- Connects to FastAPI backend for camera operations

**Key Components:**
- `create_live_view_page()` - Builds the live view UI
- `CameraSettings` - Pydantic model for camera configuration
- `create_settings_drawer()` - Settings panel for connection config

**Features:**
- Start/Stop camera
- Capture single frames
- Toggle MJPEG streaming
- Adjust refresh interval
- Configure resolution
- Real-time status indicators

#### `record_viewer.py` - Recording Playback
- Browse, play, and manage recorded surveillance footage

**Key Components:**
- `create_record_viewer_page()` - Builds the recordings browser
- `RecordingManager` - Manages recording files and metadata

**Features:**
- List all recordings with metadata (date, size)
- HTML5 video player
- Download recordings
- Delete with confirmation dialog
- Storage usage statistics

**Default Recording Path:** `/home/raspberry/recordings`

#### `record.py` - Legacy (Deprecated)
- Original recording interface (kept for backwards compatibility)
- Not used in the new modular frontend
- Use `live_view.py` instead

## Usage

### Running the Application

```bash
# Start the frontend server
python -m rpi_surveillance.ui.web
```

The application will be available at: `http://localhost:9000`

### Using in Python Code

```python
from rpi_surveillance.ui import run_app

# Start the server
run_app()
```

### Importing Components

```python
from rpi_surveillance.ui import (
    login_page,
    create_live_view_page,
    create_record_viewer_page,
)
```

## Development

### Adding a New Tab/Page

1. **Create a new module** (e.g., `analytics.py`):

```python
from nicegui import ui

def create_analytics_page():
    """Create the analytics dashboard."""
    with ui.column().classes('w-full q-pa-md'):
        ui.label('Analytics Dashboard').classes('text-h4')

        # Your UI components here
        with ui.card():
            ui.label('Detection Statistics')
            # Add charts, graphs, etc.
```

2. **Import in `web.py`**:

```python
from rpi_surveillance.ui.analytics import create_analytics_page
```

3. **Add to `main_menu()` in `web.py`**:

```python
# In the tabs section:
analytics_tab = ui.tab('Analytics', icon='analytics')

# In the tab_panels section:
with ui.tab_panel(analytics_tab):
    create_analytics_page()
```

4. **Export from `__init__.py`** (if needed elsewhere):

```python
from rpi_surveillance.ui.analytics import create_analytics_page

__all__ = [
    # ... existing exports
    'create_analytics_page',
]
```

### Best Practices

1. **Module Structure:**
   - Each module should handle one specific feature/page
   - Use `create_*_page()` naming convention for page builders
   - Keep business logic separate from UI code

2. **State Management:**
   - Use `app.storage.user` for user-specific data
   - Use Pydantic models for configuration (see `CameraSettings`)
   - Avoid global state when possible

3. **Styling:**
   - Use Quasar CSS classes (e.g., `q-pa-md`, `q-gutter-sm`)
   - Keep styling consistent across modules
   - Use Material Icons for buttons and tabs

4. **Error Handling:**
   - Always use `ui.notify()` for user feedback
   - Handle network errors gracefully
   - Provide meaningful error messages

### Testing

Test individual modules by importing and calling their page functions:

```python
from rpi_surveillance.ui import setup_auth_middleware
from rpi_surveillance.ui.live_view import create_live_view_page
from nicegui import ui

setup_auth_middleware()

@ui.page('/test')
def test_page():
    create_live_view_page()

ui.run(port=9000)
```

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│         User Browser (Port 9000)        │
└────────────────┬────────────────────────┘
                 │
                 ▼
┌─────────────────────────────────────────┐
│  web.py - Main Application              │
│  ┌────────────────────────────────────┐ │
│  │  Header (user info, logout)        │ │
│  ├────────────────────────────────────┤ │
│  │  Tabs: Home | Live | Recordings    │ │
│  └────────────────────────────────────┘ │
└──┬──────────────┬───────────────┬───────┘
   │              │               │
   ▼              ▼               ▼
┌──────┐    ┌─────────┐    ┌──────────┐
│login │    │live_view│    │record_   │
│.py   │    │.py      │    │viewer.py │
└──┬───┘    └────┬────┘    └────┬─────┘
   │             │              │
   │             ▼              │
   │      ┌────────────┐        │
   │      │  FastAPI   │        │
   │      │  Backend   │        │
   │      │ (Port 5000)│        │
   │      └─────┬──────┘        │
   │            │               │
   │            ▼               ▼
   │      ┌──────────┐    ┌─────────┐
   │      │ PiCamera2│    │Recording│
   │      │          │    │  Files  │
   │      └──────────┘    └─────────┘
   │
   ▼
┌────────────┐
│app.storage │
│   .user    │
└────────────┘
```

## Configuration

### Camera Backend
Edit `CameraSettings` in `live_view.py`:
```python
host: str = "10.10.10.13"  # FastAPI backend IP
port: int = 5000           # FastAPI backend port
```

### Recording Storage
Edit `RecordingManager` in `record_viewer.py`:
```python
recordings_dir: str = "/home/raspberry/recordings"
```

### Server Settings
Edit `run_app()` in `web.py`:
```python
ui.run(
    storage_secret='YOUR_SECRET',  # Change this!
    port=9000,
    host='0.0.0.0',
)
```

## Troubleshooting

### Login Issues
- Check that `setup_auth_middleware()` is called before page definitions
- Verify credentials in `login.py` PASSWORDS dict
- Clear browser cookies if session is stuck

### Camera Connection Issues
- Ensure FastAPI backend is running on port 5000
- Check camera settings (host/port) in live view drawer
- Verify network connectivity to camera backend

### Recording Playback Issues
- Check recording path exists: `/home/raspberry/recordings`
- Verify file permissions on recording directory
- Ensure recordings are in MP4 format

## Dependencies

- `nicegui` - Web UI framework
- `requests` - HTTP client for backend communication
- `pydantic` - Data validation and settings
- `PIL` (Pillow) - Image processing

See `requirements.txt` in project root for full dependency list.
