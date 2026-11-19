import { useRef, useState, type DragEvent } from "react";
import { Button } from "@/components/Button";
import { useT } from "@/i18n";

export function DropZone({ onFiles }: { onFiles: (files: File[]) => void }) {
  const t = useT();
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (files.length) onFiles(files);
  }

  return (
    <div
      className={"dropzone" + (over ? " dropzone-over" : "")}
      onDragOver={(e) => { e.preventDefault(); setOver(true); }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
    >
      <p className="dropzone-title">{t("import.dropTitle")}</p>
      <p className="muted">{t("import.dropHint")}</p>
      <Button variant="primary" onClick={() => input.current?.click()}>{t("import.choose")}</Button>
      <input ref={input} type="file" hidden multiple accept=".xlsx,.xlsm,.csv,.xls"
        data-testid="file-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          e.target.value = ""; // choosing the same file again must work
          if (files.length) onFiles(files);
        }} />
    </div>
  );
}
