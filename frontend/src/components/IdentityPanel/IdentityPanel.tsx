import { useEffect, useState, type ChangeEvent, type FormEvent } from "react";
import { getIdentity, updateIdentity } from "../../api/client";
import type { Identity } from "../../types";

type SaveState = "idle" | "busy" | "saved" | "failed";

const SAVE_LABELS: Record<SaveState, string> = {
  idle: "Save",
  busy: "Saving…",
  saved: "Saved ✓",
  failed: "Save failed — retry",
};

/** How long the "Saved ✓" confirmation stays before reverting. */
const CONFIRM_MS = 1500;

const EMPTY: Identity = {
  name: "",
  age: "",
  occupation: "",
  personality: "",
  interests: "",
};

const FIELDS: { key: keyof Identity; label: string }[] = [
  { key: "name", label: "Name" },
  { key: "age", label: "Age" },
  { key: "occupation", label: "Occupation" },
  { key: "personality", label: "Personality" },
  { key: "interests", label: "Interests" },
];

/**
 * Editor for the identity fields pinned into the assistant's internal chat
 * summary (Step 20). Defaults come from the backend's IDENTITY_* settings;
 * saving replaces them for the rest of the backend's lifetime.
 */
export function IdentityPanel() {
  const [fields, setFields] = useState<Identity>(EMPTY);
  const [loadError, setLoadError] = useState(false);
  const [saveState, setSaveState] = useState<SaveState>("idle");

  useEffect(() => {
    let cancelled = false;
    getIdentity()
      .then((identity) => {
        if (!cancelled) {
          setFields(identity);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setLoadError(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (saveState !== "saved") {
      return undefined;
    }
    const timer = window.setTimeout(() => setSaveState("idle"), CONFIRM_MS);
    return () => window.clearTimeout(timer);
  }, [saveState]);

  const edit =
    (key: keyof Identity) => (event: ChangeEvent<HTMLInputElement>) => {
      setFields((current) => ({ ...current, [key]: event.target.value }));
    };

  const save = (event: FormEvent) => {
    event.preventDefault();
    setSaveState("busy");
    updateIdentity(fields)
      .then((saved) => {
        setFields(saved); // server-stripped values
        setSaveState("saved");
      })
      .catch(() => setSaveState("failed"));
  };

  return (
    <aside className="identity-panel" aria-label="Identity">
      <h2>Identity</h2>
      <p className="identity-hint">
        These details stay with the assistant even after the chat summary is
        cleared.
      </p>
      {loadError && (
        <p className="identity-error">
          Could not load the current identity; saving will still replace it.
        </p>
      )}
      <form onSubmit={save}>
        {FIELDS.map(({ key, label }) => (
          <label key={key}>
            {label}
            <input
              type="text"
              value={fields[key]}
              maxLength={200}
              onChange={edit(key)}
            />
          </label>
        ))}
        <button type="submit" disabled={saveState === "busy"}>
          {SAVE_LABELS[saveState]}
        </button>
      </form>
    </aside>
  );
}
