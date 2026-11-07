export interface FileUpload {
  files: readonly File[];
  body: string;
  title: string | null;
  description: string | null;
  includeScreen?: boolean;
}
