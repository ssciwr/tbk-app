export type CameraProfile = 'patient-data' | 'camera';

const CAMERA_DEVICE_KEY_PREFIX = 'teddy_camera_device_';
const CAMERA_PROFILE_VERSION_KEY = 'teddy_camera_profile_version';
const CAMERA_KNOWN_DEVICES_KEY = 'teddy_camera_known_devices';
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

function readKnownDeviceIds(): string[] {
  if (typeof window === 'undefined') {
    return [];
  }

  const raw = window.localStorage.getItem(CAMERA_KNOWN_DEVICES_KEY);
  if (!raw) {
    return [];
  }

  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed.filter((value): value is string => typeof value === 'string' && Boolean(value));
  } catch {
    return [];
  }
}

function writeKnownDeviceIds(deviceIds: string[]): void {
  if (typeof window === 'undefined') {
    return;
  }

  if (deviceIds.length === 0) {
    window.localStorage.removeItem(CAMERA_KNOWN_DEVICES_KEY);
    return;
  }

  window.localStorage.setItem(CAMERA_KNOWN_DEVICES_KEY, JSON.stringify(deviceIds));
}

function mergeUniqueDeviceIds(primary: string[], secondary: string[] = []): string[] {
  const merged: string[] = [];
  const seen = new Set<string>();

  for (const deviceId of [...primary, ...secondary]) {
    if (!deviceId || seen.has(deviceId)) {
      continue;
    }
    seen.add(deviceId);
    merged.push(deviceId);
  }

  return merged;
}

function rememberKnownDeviceId(deviceId: string | null | undefined): void {
  if (!deviceId) {
    return;
  }
  const known = readKnownDeviceIds();
  writeKnownDeviceIds(mergeUniqueDeviceIds(known, [deviceId]));
}

function rememberKnownDeviceIds(deviceIds: string[]): void {
  if (deviceIds.length === 0) {
    return;
  }
  const known = readKnownDeviceIds();
  writeKnownDeviceIds(mergeUniqueDeviceIds(known, deviceIds));
}

function forgetKnownDeviceId(deviceId: string): void {
  const known = readKnownDeviceIds();
  const filtered = known.filter((id) => id !== deviceId);
  writeKnownDeviceIds(filtered);
}

export function clearStoredCameraSelections(): void {
  if (typeof window === 'undefined') {
    return;
  }
  clearStoredDeviceId('patient-data');
  clearStoredDeviceId('camera');
  window.localStorage.removeItem(CAMERA_KNOWN_DEVICES_KEY);
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

async function listVideoInputDeviceIds(): Promise<string[]> {
  if (!navigator.mediaDevices?.enumerateDevices) {
    return [];
  }

  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((device) => device.kind === 'videoinput' && Boolean(device.deviceId))
    .map((device) => device.deviceId);
}

function switchCandidates(deviceIds: string[], currentDeviceId: string | null): string[] {
  if (!currentDeviceId) {
    return [...deviceIds];
  }

  const currentIndex = deviceIds.indexOf(currentDeviceId);
  if (currentIndex === -1) {
    return [...deviceIds];
  }

  return [...deviceIds.slice(currentIndex + 1), ...deviceIds.slice(0, currentIndex)];
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
    const activeDeviceId = track.getSettings().deviceId;
    storeDeviceId(profile, activeDeviceId);
    rememberKnownDeviceId(activeDeviceId);
  }

  try {
    rememberKnownDeviceIds(await listVideoInputDeviceIds());
  } catch {
    // Keep operating with whichever device was opened successfully.
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

export async function switchProfiledCamera(
  profile: CameraProfile,
  currentStream: MediaStream | null,
  videoEl: HTMLVideoElement | null
): Promise<MediaStream> {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Webcam API not available');
  }

  const currentTrack = currentStream?.getVideoTracks()[0] ?? null;
  const currentDeviceId = currentTrack?.getSettings().deviceId ?? null;
  let enumeratedDeviceIds: string[] = [];
  try {
    enumeratedDeviceIds = await listVideoInputDeviceIds();
    rememberKnownDeviceIds(enumeratedDeviceIds);
  } catch {
    // Fallback to remembered device IDs only.
  }
  const knownDeviceIds = readKnownDeviceIds();
  const allCandidates = mergeUniqueDeviceIds(enumeratedDeviceIds, knownDeviceIds);
  const candidates = switchCandidates(allCandidates, currentDeviceId);

  if (candidates.length === 0 || (candidates.length === 1 && candidates[0] === currentDeviceId)) {
    throw new Error('No alternative camera available');
  }

  for (const candidate of candidates) {
    if (!candidate || candidate === currentDeviceId) {
      continue;
    }

    try {
      const nextStream = await openStream(exactDeviceConstraints(candidate));
      const track = nextStream.getVideoTracks()[0];
      if (track) {
        try {
          await track.applyConstraints(baseSquareConstraints());
        } catch {
          // Not all cameras/browsers support these constraints.
        }
        const activeDeviceId = track.getSettings().deviceId;
        storeDeviceId(profile, activeDeviceId);
        rememberKnownDeviceId(activeDeviceId);
      }

      if (videoEl) {
        videoEl.srcObject = nextStream;
        await videoEl.play();
      }

      return nextStream;
    } catch (error) {
      if (isStaleDeviceError(error)) {
        forgetKnownDeviceId(candidate);
      }
    }
  }

  throw new Error('No alternative camera available');
}
