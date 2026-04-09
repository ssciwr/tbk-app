export type CaseDisplayMetadata = {
  child_name?: string;
  animal_name?: string;
};

export function hasText(value: string | null | undefined): boolean {
  return Boolean(value?.trim());
}

export function formatCaseSubject(
  metadata: CaseDisplayMetadata,
  fallback = 'QR-only case'
): string {
  const childName = metadata.child_name?.trim() ?? '';
  const animalName = metadata.animal_name?.trim() ?? '';

  if (childName && animalName) {
    return `${childName} / ${animalName}`;
  }

  return childName || animalName || fallback;
}

export function isQrOnlyCase(metadata: CaseDisplayMetadata): boolean {
  return !hasText(metadata.child_name) && !hasText(metadata.animal_name);
}
