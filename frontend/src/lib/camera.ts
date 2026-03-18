export type CameraProfile = 'patient-data' | 'camera';

const CAMERA_DEVICE_KEY_PREFIX = 'teddy_camera_device_';
const CAMERA_PROFILE_VERSION_KEY = 'teddy_camera_profile_version';
const CAMERA_PROFILE_VERSION = '2';

function getStorageKey(profile: CameraProfile): string {
  return `${CAMERA_DEVICE_KEY_PREFIX}${profile}`;
}

function migrateStoredProfiles(): void {
  if (typeof window === 'undefined') {
    return;
  }
  const currentVersion = window.localStorage.getItem(CAMERA_PROFILE_VERSION_KEY);
  if (currentVersion === CAMERA_PROFILE_VERSION) {
    return;
  }

  window.localStorage.removeItem(getStorageKey('patient-data'));
  window.localStorage.removeItem(getStorageKey('camera'));
  window.localStorage.setItem(CAMERA_PROFILE_VERSION_KEY, CAMERA_PROFILE_VERSION);
}

function readStoredDeviceId(profile: CameraProfile): string | null {
  if (typeof window === 'undefined') {
    return null;
  }
  return window.localStorage.getItem(getStorageKey(profile));
}

function storeDeviceId(profile: CameraProfile, deviceId: string | undefined): void {
  if (typeof window === 'undefined' || !deviceId) {
    return;
  }
  window.localStorage.setItem(getStorageKey(profile), deviceId);
}

function clearStoredDeviceId(profile: CameraProfile): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.localStorage.removeItem(getStorageKey(profile));
}

function getOtherProfile(profile: CameraProfile): CameraProfile {
  return profile === 'patient-data' ? 'camera' : 'patient-data';
}

function baseSquareConstraints(): Pick<
  MediaTrackConstraints,
  'aspectRatio' | 'width' | 'height'
> {
  return {
    aspectRatio: { ideal: 1 },
    width: { ideal: 1080 },
    height: { ideal: 1080 }
  };
}

function preferredConstraints(): MediaTrackConstraints {
  return {
    ...baseSquareConstraints(),
    facingMode: { ideal: 'environment' }
  };
}

function exactDeviceConstraints(deviceId: string): MediaTrackConstraints {
  return {
    ...baseSquareConstraints(),
    deviceId: { exact: deviceId }
  };
}

async function chooseAlternativeDeviceId(excludedDeviceId: string): Promise<string | null> {
  if (!navigator.mediaDevices?.enumerateDevices) {
    return null;
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  const videoInputs = devices.filter(
    (device) => device.kind === 'videoinput' && Boolean(device.deviceId)
  );
  const alternative = videoInputs.find((device) => device.deviceId !== excludedDeviceId);
  return alternative?.deviceId || null;
}

function isStaleDeviceError(error: unknown): boolean {
  if (!(error instanceof DOMException)) {
    return false;
  }
  return error.name === 'NotFoundError' || error.name === 'OverconstrainedError';
}

async function openStream(constraints: MediaTrackConstraints): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia({
    video: constraints,
    audio: false
  });
}

export async function startProfiledCamera(
  profile: CameraProfile,
  videoEl: HTMLVideoElement | null
): Promise<MediaStream> {
  migrateStoredProfiles();
  const savedDeviceId = readStoredDeviceId(profile);
  const otherProfileDeviceId = readStoredDeviceId(getOtherProfile(profile));
  let stream: MediaStream | null = null;

  if (savedDeviceId) {
    try {
      stream = await openStream(exactDeviceConstraints(savedDeviceId));
    } catch (error) {
      if (isStaleDeviceError(error)) {
        clearStoredDeviceId(profile);
      }
    }
  }

  if (!stream) {
    // For the first /camera visit, try to avoid reusing the /patient-data device.
    if (!savedDeviceId && profile === 'camera' && otherProfileDeviceId) {
      try {
        const alternativeDeviceId = await chooseAlternativeDeviceId(otherProfileDeviceId);
        if (alternativeDeviceId) {
          stream = await openStream(exactDeviceConstraints(alternativeDeviceId));
        }
      } catch {
        // Continue with generic fallbacks.
      }
    }
  }

  if (!stream) {
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: true,
        audio: false
      });
    } catch {
      // Try environment preference fallback.
    }
  }

  if (!stream) {
    try {
      stream = await openStream(preferredConstraints());
    } catch {
      // Handled below.
    }
  }

  if (!stream) {
    throw new Error('Could not access webcam');
  }

  const track = stream.getVideoTracks()[0];
  if (track) {
    try {
      await track.applyConstraints(baseSquareConstraints());
    } catch {
      // Not all cameras/browsers support these constraints.
    }
    storeDeviceId(profile, track.getSettings().deviceId);
  }

  if (videoEl) {
    videoEl.srcObject = stream;
    await videoEl.play();
  }

  return stream;
}

export function rememberProfiledCamera(
  profile: CameraProfile,
  stream: MediaStream | null
): void {
  if (!stream) {
    return;
  }
  const track = stream.getVideoTracks()[0];
  if (!track) {
    return;
  }
  storeDeviceId(profile, track.getSettings().deviceId);
}
