/**
 * Getting a folder out of a browser, which is harder than it should be.
 *
 * A merchant's books are a folder. That is how the command line takes them
 * and it is how they exist on disk — `Downloads/july-2026/` with a settlement
 * report, a statement, and whatever else the finance team saved there. The
 * dialog took files one at a time, so handing over five of them meant five
 * trips through a file picker, and the folder somebody actually had was not
 * something they could give us at all.
 *
 * Two paths, because browsers give a folder in two different shapes:
 *
 * **The picker** returns a flat `FileList` where each file carries a
 * `webkitRelativePath`. Nothing to walk — the browser already did.
 *
 * **A drop** returns `DataTransferItem`s, and a dropped folder is an *entry*
 * that has to be read recursively. `webkitGetAsEntry` is prefixed and
 * non-standard and is also the only thing every browser implements, so it is
 * what this uses, with a plain-files fallback for anything that does not.
 *
 * Both paths filter. A real folder holds a `.DS_Store`, a logo, a zip of last
 * quarter, and Excel's lock files — sending those to be refused one by one
 * would turn a working folder into a screen of errors about files nobody
 * meant to hand over.
 */

/** Extensions worth sending. Anything else in the folder is not ours. */
const READABLE = [".csv", ".tsv", ".txt", ".xlsx", ".xlsm"];

/**
 * Formats somebody could reasonably think they had handed their books over
 * in. These are sent *deliberately* so the engine can refuse each with the
 * sentence that gets the person unstuck — silently dropping a PDF bank
 * statement is how a run ends up covering a month with no bank side and
 * nothing anywhere saying why.
 */
const WORTH_REFUSING = [".pdf", ".xls", ".json", ".zip"];

const WANTED = [...READABLE, ...WORTH_REFUSING];

/** How deep into a dropped folder to walk. A books folder is not a tree. */
const MAX_DEPTH = 3;

/** Files past this are not read; the engine's own cap is the real one. */
const MAX_FILES = 40;

function wanted(name: string): boolean {
  const lowered = name.toLowerCase();
  // `~$name.xlsx` is the lock file Excel leaves beside a workbook somebody has
  // open, and dropping a folder while the statement is open is not unusual.
  if (lowered.startsWith("~$") || lowered.startsWith(".")) return false;
  return WANTED.some((suffix) => lowered.endsWith(suffix));
}

/** Whether this file is one the engine can read, rather than merely refuse. */
export function readable(file: File): boolean {
  const lowered = file.name.toLowerCase();
  return READABLE.some((suffix) => lowered.endsWith(suffix));
}

export function keep(files: File[]): File[] {
  return files.filter((file) => wanted(file.name)).slice(0, MAX_FILES);
}

/*
  `FileSystemEntry` and friends are in `lib.dom` already, so nothing is
  declared here. The one thing that is not typed is `webkitGetAsEntry` being
  absent: it is non-standard, every browser implements it, and a browser that
  does not cannot give us a folder at all - so the call is guarded and the
  fallback is plain files.
*/

const asFile = (entry: FileSystemFileEntry): Promise<File | null> =>
  new Promise((resolve) => {
    entry.file(
      (file) => resolve(file),
      () => resolve(null),
    );
  });

/**
 * One directory's entries.
 *
 * `readEntries` returns at most a hundred at a time and signals the end with
 * an empty array, so it has to be called until it does. A single call reads a
 * folder of five files correctly and loses everything past the hundredth in a
 * folder of two hundred, which is the kind of bug that only appears on
 * somebody else's data.
 */
async function children(entry: FileSystemDirectoryEntry): Promise<FileSystemEntry[]> {
  const reader = entry.createReader();
  const found: FileSystemEntry[] = [];
  for (;;) {
    const batch = await new Promise<FileSystemEntry[]>((resolve) => {
      reader.readEntries(
        (entries) => resolve(entries),
        () => resolve([]),
      );
    });
    if (batch.length === 0) return found;
    found.push(...batch);
    if (found.length > MAX_FILES * 4) return found;
  }
}

async function walk(entry: FileSystemEntry, depth: number): Promise<File[]> {
  if (entry.isFile) {
    if (!wanted(entry.name)) return [];
    const file = await asFile(entry as FileSystemFileEntry);
    return file ? [file] : [];
  }
  if (!entry.isDirectory || depth >= MAX_DEPTH) return [];
  const found: File[] = [];
  for (const child of await children(entry as FileSystemDirectoryEntry)) {
    found.push(...(await walk(child, depth + 1)));
  }
  return found;
}

/**
 * Every file worth reading out of a drop, folders walked.
 *
 * Falls back to `dataTransfer.files` when the entry API is missing, which
 * loses folder support and keeps plain files working — the right way round,
 * since a browser without `webkitGetAsEntry` cannot give us a folder anyway.
 */
export async function fromDrop(transfer: DataTransfer): Promise<File[]> {
  const entries = [...transfer.items]
    .filter((item) => item.kind === "file")
    .map((item) => item.webkitGetAsEntry?.() ?? null)
    .filter((entry): entry is FileSystemEntry => entry !== null);

  if (entries.length === 0) return keep([...transfer.files]);

  const found: File[] = [];
  for (const entry of entries) found.push(...(await walk(entry, 0)));
  return found.slice(0, MAX_FILES);
}
