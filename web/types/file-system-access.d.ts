/**
 * The parts of the File System Access API that TypeScript 5.9 does not ship.
 *
 * `lib.dom` has `FileSystemDirectoryHandle` and `FileSystemFileHandle`, but
 * not `showDirectoryPicker` and not the async iterator that makes a directory
 * handle readable. Both are Chromium-only, which is presumably why: they are
 * a live standards proposal rather than a settled standard.
 *
 * Declared here rather than cast away at the call site so the walk is
 * type-checked like everything else, and so the one place that knows this API
 * is provisional is a file whose name says so.
 */

declare global {
  interface FileSystemDirectoryHandle {
    /** Every child handle, files and directories alike. */
    values(): AsyncIterableIterator<FileSystemDirectoryHandle | FileSystemFileHandle>;
  }

  interface Window {
    showDirectoryPicker(options?: {
      /** Reopens at the folder last chosen under this id. */
      id?: string;
      mode?: "read" | "readwrite";
      startIn?: FileSystemHandle | string;
    }): Promise<FileSystemDirectoryHandle>;
  }
}

export {};
