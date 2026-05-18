const DEFAULT_MAX_SIDE = 1080;
const DEFAULT_QUALITY = 0.84;
const ENCODE_TYPES = ['image/webp', 'image/jpeg', 'image/png'] as const;

type EncodeOptions = {
  maxSide?: number;
  quality?: number;
  basename?: string;
};

export function imageExtensionForType(type: string): string {
  if (type === 'image/webp') {
    return 'webp';
  }
  if (type === 'image/jpeg') {
    return 'jpg';
  }
  return 'png';
}

function targetSize(width: number, height: number, maxSide: number): { width: number; height: number } {
  const longestSide = Math.max(width, height);
  if (longestSide <= maxSide) {
    return { width, height };
  }
  const scale = maxSide / longestSide;
  return {
    width: Math.max(1, Math.round(width * scale)),
    height: Math.max(1, Math.round(height * scale))
  };
}

function createResizedCanvas(
  source: CanvasImageSource,
  width: number,
  height: number,
  maxSide: number
): HTMLCanvasElement | null {
  const size = targetSize(width, height, maxSide);
  const canvas = document.createElement('canvas');
  canvas.width = size.width;
  canvas.height = size.height;
  const context = canvas.getContext('2d');
  if (!context) {
    return null;
  }
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, size.width, size.height);
  context.drawImage(source, 0, 0, width, height, 0, 0, size.width, size.height);
  return canvas;
}

async function canvasToBlob(
  canvas: HTMLCanvasElement,
  type: string,
  quality: number
): Promise<Blob | null> {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), type, quality);
  });
}

async function encodeCanvas(canvas: HTMLCanvasElement, quality: number): Promise<Blob | null> {
  for (const type of ENCODE_TYPES) {
    const blob = await canvasToBlob(canvas, type, quality);
    if (blob && (type === 'image/png' || blob.type === type)) {
      return blob;
    }
  }
  return null;
}

export async function canvasToUploadBlob(
  sourceCanvas: HTMLCanvasElement,
  options: EncodeOptions = {}
): Promise<Blob | null> {
  const maxSide = options.maxSide ?? DEFAULT_MAX_SIDE;
  const quality = options.quality ?? DEFAULT_QUALITY;
  const canvas =
    createResizedCanvas(sourceCanvas, sourceCanvas.width, sourceCanvas.height, maxSide) ?? sourceCanvas;
  return encodeCanvas(canvas, quality);
}

function loadImageFromFile(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('Failed to load image file'));
    };
    image.src = objectUrl;
  });
}

function stemFromFilename(filename: string): string {
  return filename.replace(/\.[^.]+$/, '') || 'image';
}

export async function compressImageFileForUpload(
  file: File,
  options: EncodeOptions = {}
): Promise<File> {
  if (!file.type.startsWith('image/')) {
    return file;
  }

  const image = await loadImageFromFile(file);
  const canvas = createResizedCanvas(
    image,
    image.naturalWidth || image.width,
    image.naturalHeight || image.height,
    options.maxSide ?? DEFAULT_MAX_SIDE
  );
  if (!canvas) {
    return file;
  }

  const blob = await encodeCanvas(canvas, options.quality ?? DEFAULT_QUALITY);
  if (!blob || blob.size >= file.size) {
    return file;
  }

  const basename = options.basename ?? stemFromFilename(file.name);
  const extension = imageExtensionForType(blob.type);
  return new File([blob], `${basename}.${extension}`, { type: blob.type });
}
