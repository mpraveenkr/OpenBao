const { useEffect, useMemo, useState } = React;

const emptyColumn = () => ({
  column_name: "",
  source_column_name: "",
  type: "string",
  nullable: true,
  mask_policy: "none",
  primary_key: false,
  watermark: false,
  notes: "",
});

const defaultDefinition = () => ({
  object_id: "sample_csv_customers",
  source_system: "sample_files",
  source_type: "file",
  object_name: "customers",
  enabled: true,
  load_strategy: "full",
  extraction: {
    file_type: "csv",
    path: "data/input/customers.csv",
    delimiter: ",",
    header: true,
    encoding: "utf-8",
  },
  schema_policy: {
    mode: "explicit",
    column_case: "snake_case",
    replace_spaces_with: "_",
    allow_schema_evolution: true,
    include_unmodeled_columns: false,
    infer_types: false,
  },
  columns: [
    { column_name: "customer_id", source_column_name: "Customer ID", type: "string", nullable: false, mask_policy: "none", primary_key: true, watermark: false, notes: "" },
    { column_name: "customer_name", source_column_name: "Customer Name", type: "string", nullable: true, mask_policy: "none", primary_key: false, watermark: false, notes: "" },
    { column_name: "created_date", source_column_name: "Created Date", type: "date", nullable: true, mask_policy: "none", primary_key: false, watermark: false, notes: "" },
    { column_name: "updated_timestamp", source_column_name: "Updated Timestamp", type: "timestamp", nullable: true, mask_policy: "none", primary_key: false, watermark: false, notes: "" },
  ],
  target: {
    storage_name: "local_bronze",
    zone: "bronze",
    format: "parquet",
    write_mode: "append",
    compression: "snappy",
    partition_by: ["ingest_year", "ingest_month", "ingest_day"],
  },
  audit: {
    dq_checks: ["row_count_gt_zero"],
  },
  security: {
    classification: "internal",
    contains_bcsi: false,
    contains_pii: false,
    encryption_required: false,
    masking_required: false,
    raw_payload_retention_days: 30,
    access_group: "local_ingestion_developers",
  },
});

function App() {
  const [definitions, setDefinitions] = useState([]);
  const [selectedId, setSelectedId] = useState(null);
  const [definition, setDefinition] = useState(defaultDefinition());
  const [yamlPreview, setYamlPreview] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => {
    refreshDefinitions();
  }, []);

  useEffect(() => {
    const selected = definitions.find((item) => item.id === selectedId);
    if (selected) {
      setDefinition(selected.definition);
    }
  }, [selectedId, definitions]);

  const selectedRecord = useMemo(
    () => definitions.find((item) => item.id === selectedId),
    [definitions, selectedId],
  );

  async function refreshDefinitions() {
    const response = await fetch("/api/source-definitions");
    const data = await response.json();
    setDefinitions(data);
  }

  function setField(path, value) {
    setDefinition((current) => updatePath(current, path, value));
  }

  function newDefinition() {
    setSelectedId(null);
    setDefinition(defaultDefinition());
    setYamlPreview("");
    setMessage("Started a new source definition.");
  }

  async function saveDefinition() {
    const body = selectedId
      ? { payload: sanitizeDefinition(definition), updated_by: "local_user" }
      : { payload: sanitizeDefinition(definition), created_by: "local_user" };
    const response = await fetch(
      selectedId ? `/api/source-definitions/${selectedId}` : "/api/source-definitions",
      {
        method: selectedId ? "PUT" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      },
    );
    if (!response.ok) {
      setMessage(`Save failed: ${await response.text()}`);
      return;
    }
    const record = await response.json();
    setSelectedId(record.id);
    await refreshDefinitions();
    setMessage("Source definition saved.");
  }

  async function deleteDefinition() {
    if (!selectedId) return;
    const response = await fetch(`/api/source-definitions/${selectedId}`, { method: "DELETE" });
    if (!response.ok) {
      setMessage("Delete failed.");
      return;
    }
    setSelectedId(null);
    setDefinition(defaultDefinition());
    await refreshDefinitions();
    setMessage("Source definition deleted.");
  }

  async function loadYaml() {
    if (!selectedId) {
      await saveDefinition();
      return;
    }
    const response = await fetch(`/api/source-definitions/${selectedId}/yaml`);
    setYamlPreview(await response.text());
    setMessage("YAML preview refreshed.");
  }

  async function exportYaml() {
    if (!selectedId) {
      setMessage("Save the definition before exporting YAML.");
      return;
    }
    const response = await fetch(`/api/source-definitions/${selectedId}/export-yaml`, { method: "POST" });
    if (!response.ok) {
      setMessage("YAML export failed.");
      return;
    }
    const result = await response.json();
    setMessage(`YAML exported to ${result.path}`);
  }

  function addColumn() {
    setDefinition((current) => ({ ...current, columns: [...current.columns, emptyColumn()] }));
  }

  function updateColumn(index, field, value) {
    setDefinition((current) => ({
      ...current,
      columns: current.columns.map((column, columnIndex) =>
        columnIndex === index ? { ...column, [field]: value } : column,
      ),
    }));
  }

  function removeColumn(index) {
    setDefinition((current) => ({
      ...current,
      columns: current.columns.filter((_, columnIndex) => columnIndex !== index),
    }));
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <strong>Ingestion Metadata Manager</strong>
          <span>Capture source definitions and generate framework YAML</span>
        </div>
        <span className="status">Local SQLite persistence</span>
      </header>

      <div className="layout">
        <aside className="sidebar">
          <div className="sidebar-actions">
            <button className="primary" onClick={newDefinition}>New</button>
            <button onClick={refreshDefinitions}>Refresh</button>
          </div>
          <div className="source-list">
            {definitions.length === 0 && <p className="hint">No saved source definitions yet.</p>}
            {definitions.map((item) => (
              <button
                className={`source-row ${item.id === selectedId ? "active" : ""}`}
                key={item.id}
                onClick={() => setSelectedId(item.id)}
              >
                <strong>{item.object_id}</strong>
                <span>{item.source_type} · {item.source_system} · {item.object_name}</span>
              </button>
            ))}
          </div>
        </aside>

        <main className="main">
          <div className="toolbar">
            <div>
              <h1>{selectedRecord ? selectedRecord.object_id : "New source definition"}</h1>
              <span className="hint">CSV/file source is executable today. Database and API metadata can be captured for future milestones.</span>
            </div>
            <div className="actions">
              <button className="primary" onClick={saveDefinition}>Save</button>
              <button onClick={loadYaml}>Preview YAML</button>
              <button onClick={exportYaml}>Export YAML</button>
              <button className="danger" onClick={deleteDefinition} disabled={!selectedId}>Delete</button>
            </div>
          </div>

          {message && <div className={`message ${message.includes("failed") ? "warn" : "ok"}`}>{message}</div>}

          <Section title="Source Object">
            <div className="grid">
              <TextInput label="Object ID" value={definition.object_id} onChange={(value) => setField("object_id", value)} />
              <TextInput label="Source System" value={definition.source_system} onChange={(value) => setField("source_system", value)} />
              <SelectInput label="Source Type" value={definition.source_type} options={["file", "database", "api"]} onChange={(value) => setField("source_type", value)} />
              <TextInput label="Object Name" value={definition.object_name} onChange={(value) => setField("object_name", value)} />
              <SelectInput label="Load Strategy" value={definition.load_strategy} options={["full", "incremental", "snapshot"]} onChange={(value) => setField("load_strategy", value)} />
              <SelectInput label="Enabled" value={String(definition.enabled)} options={["true", "false"]} onChange={(value) => setField("enabled", value === "true")} />
            </div>
          </Section>

          <ExtractionSection definition={definition} setField={setField} />

          <Section title="Schema Policy" hint="Use infer to ingest every source column/field; use hybrid to ingest all fields but override selected columns.">
            <div className="grid three">
              <SelectInput label="Mode" value={definition.schema_policy.mode || "explicit"} options={["explicit", "infer", "hybrid"]} onChange={(value) => setField("schema_policy.mode", value)} />
              <SelectInput label="Include Unmodeled Columns" value={String(Boolean(definition.schema_policy.include_unmodeled_columns))} options={["true", "false"]} onChange={(value) => setField("schema_policy.include_unmodeled_columns", value === "true")} />
              <SelectInput label="Infer Types" value={String(Boolean(definition.schema_policy.infer_types))} options={["true", "false"]} onChange={(value) => setField("schema_policy.infer_types", value === "true")} />
              <SelectInput label="Allow Schema Evolution" value={String(Boolean(definition.schema_policy.allow_schema_evolution))} options={["true", "false"]} onChange={(value) => setField("schema_policy.allow_schema_evolution", value === "true")} />
              <TextInput label="Column Case" value={definition.schema_policy.column_case || "snake_case"} onChange={(value) => setField("schema_policy.column_case", value)} />
              <TextInput label="Replace Spaces With" value={definition.schema_policy.replace_spaces_with || "_"} onChange={(value) => setField("schema_policy.replace_spaces_with", value)} />
            </div>
          </Section>

          <Section
            title="Columns"
            hint="In infer mode this can stay empty. In hybrid mode, enter only primary keys, watermarks, masks, and type overrides."
            action={<button onClick={addColumn}>Add Column</button>}
          >
            <ColumnEditor columns={definition.columns} updateColumn={updateColumn} removeColumn={removeColumn} />
          </Section>

          <TargetSection definition={definition} setField={setField} />
          <AuditSecuritySection definition={definition} setField={setField} />

          <Section title="Generated YAML">
            <pre className="yaml-preview">{yamlPreview || "Save, then use Preview YAML to see the generated config."}</pre>
          </Section>
        </main>
      </div>
    </div>
  );
}

function Section({ title, hint, action, children }) {
  return (
    <section className="section">
      <div className="section-header">
        <div>
          <h2>{title}</h2>
          {hint && <span className="hint">{hint}</span>}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}

function ExtractionSection({ definition, setField }) {
  if (definition.source_type === "database") {
    return (
      <Section title="Database Extraction" hint="Capture only in this milestone; database extraction is not executable yet.">
        <div className="grid two">
          <SelectInput label="DB Type" value={definition.extraction.db_type || "postgresql"} options={["postgresql", "mysql", "oracle", "sql_server", "sqlite", "other"]} onChange={(value) => setField("extraction.db_type", value)} />
          <TextInput label="Connection Name" value={definition.extraction.connection_name || ""} onChange={(value) => setField("extraction.connection_name", value)} />
          <TextInput label="Schema Name" value={definition.extraction.schema_name || ""} onChange={(value) => setField("extraction.schema_name", value)} />
          <TextInput label="Table/View Name" value={definition.extraction.table_name || ""} onChange={(value) => setField("extraction.table_name", value)} />
          <TextInput label="Incremental Column" value={definition.extraction.incremental_column || ""} onChange={(value) => setField("extraction.incremental_column", value)} />
          <TextInput label="Fetch Size" value={definition.extraction.fetch_size || ""} onChange={(value) => setField("extraction.fetch_size", Number(value) || "")} />
          <TextArea label="Query" value={definition.extraction.query || ""} onChange={(value) => setField("extraction.query", value)} />
        </div>
      </Section>
    );
  }

  if (definition.source_type === "api") {
    return (
      <Section title="API Extraction" hint="Capture only in this milestone; API extraction is not executable yet.">
        <div className="grid two">
          <TextInput label="Base URL" value={definition.extraction.base_url || ""} onChange={(value) => setField("extraction.base_url", value)} />
          <TextInput label="Endpoint" value={definition.extraction.endpoint || ""} onChange={(value) => setField("extraction.endpoint", value)} />
          <SelectInput label="Method" value={definition.extraction.method || "GET"} options={["GET", "POST"]} onChange={(value) => setField("extraction.method", value)} />
          <SelectInput label="Auth Type" value={definition.extraction.auth_type || "none"} options={["none", "api_key", "bearer_token", "oauth2_client_credentials", "basic"]} onChange={(value) => setField("extraction.auth_type", value)} />
          <TextInput label="Connection Name" value={definition.extraction.connection_name || ""} onChange={(value) => setField("extraction.connection_name", value)} />
          <TextInput label="Response Record Path" value={definition.extraction.response_record_path || "$.data[*]"} onChange={(value) => setField("extraction.response_record_path", value)} />
          <TextInput label="Pagination Type" value={definition.extraction.pagination_type || "none"} onChange={(value) => setField("extraction.pagination_type", value)} />
          <TextInput label="Incremental Parameter" value={definition.extraction.incremental_parameter || ""} onChange={(value) => setField("extraction.incremental_parameter", value)} />
        </div>
      </Section>
    );
  }

  return (
    <Section title="CSV/File Extraction">
      <div className="grid">
        <SelectInput label="File Type" value={definition.extraction.file_type || "csv"} options={["csv", "delimited", "fixed_width", "json", "xml", "excel"]} onChange={(value) => setField("extraction.file_type", value)} />
        <TextInput label="Path" value={definition.extraction.path || ""} onChange={(value) => setField("extraction.path", value)} />
        <TextInput label="Delimiter" value={definition.extraction.delimiter || ","} onChange={(value) => setField("extraction.delimiter", value)} />
        <SelectInput label="Header" value={String(definition.extraction.header ?? true)} options={["true", "false"]} onChange={(value) => setField("extraction.header", value === "true")} />
        <TextInput label="Encoding" value={definition.extraction.encoding || "utf-8"} onChange={(value) => setField("extraction.encoding", value)} />
      </div>
    </Section>
  );
}

function ColumnEditor({ columns, updateColumn, removeColumn }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table className="column-table">
        <thead>
          <tr>
            <th>Column</th>
            <th>Source Column</th>
            <th>Type</th>
            <th>Nullable</th>
            <th>Mask Policy</th>
            <th>Primary Key</th>
            <th>Watermark</th>
            <th>Notes</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {columns.map((column, index) => (
            <tr key={index}>
              <td><input value={column.column_name} onChange={(event) => updateColumn(index, "column_name", event.target.value)} /></td>
              <td><input value={column.source_column_name || ""} onChange={(event) => updateColumn(index, "source_column_name", event.target.value)} /></td>
              <td>
                <select value={column.type} onChange={(event) => updateColumn(index, "type", event.target.value)}>
                  {["string", "integer", "bigint", "decimal", "float", "boolean", "date", "timestamp"].map((item) => <option key={item}>{item}</option>)}
                </select>
              </td>
              <td className="check-cell"><input type="checkbox" checked={column.nullable} onChange={(event) => updateColumn(index, "nullable", event.target.checked)} /></td>
              <td>
                <select value={column.mask_policy || "none"} onChange={(event) => updateColumn(index, "mask_policy", event.target.value)}>
                  {["none", "redact", "hash", "tokenize", "partial"].map((item) => <option key={item}>{item}</option>)}
                </select>
              </td>
              <td className="check-cell"><input type="checkbox" checked={column.primary_key} onChange={(event) => updateColumn(index, "primary_key", event.target.checked)} /></td>
              <td className="check-cell"><input type="checkbox" checked={column.watermark} onChange={(event) => updateColumn(index, "watermark", event.target.checked)} /></td>
              <td><input value={column.notes || ""} onChange={(event) => updateColumn(index, "notes", event.target.value)} /></td>
              <td><button className="icon danger" title="Remove column" onClick={() => removeColumn(index)}>×</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TargetSection({ definition, setField }) {
  return (
    <Section title="Target">
      <div className="grid three">
        <TextInput label="Storage Name" value={definition.target.storage_name || "local_bronze"} onChange={(value) => setField("target.storage_name", value)} />
        <TextInput label="Zone" value={definition.target.zone || "bronze"} onChange={(value) => setField("target.zone", value)} />
        <SelectInput label="Format" value={definition.target.format || "parquet"} options={["parquet"]} onChange={(value) => setField("target.format", value)} />
        <SelectInput label="Write Mode" value={definition.target.write_mode || "append"} options={["append", "overwrite"]} onChange={(value) => setField("target.write_mode", value)} />
        <SelectInput label="Compression" value={definition.target.compression || "snappy"} options={["snappy", "gzip", "none"]} onChange={(value) => setField("target.compression", value)} />
        <TextInput label="Partition By" value={arrayToCsv(definition.target.partition_by)} onChange={(value) => setField("target.partition_by", csvToArray(value))} />
      </div>
    </Section>
  );
}

function AuditSecuritySection({ definition, setField }) {
  return (
    <Section title="Audit and Security">
      <div className="grid">
        <TextInput label="DQ Checks" value={arrayToCsv(definition.audit.dq_checks)} onChange={(value) => setField("audit.dq_checks", csvToArray(value))} />
        <SelectInput label="Classification" value={definition.security.classification || "internal"} options={["public", "internal", "confidential", "restricted", "bcsi"]} onChange={(value) => setField("security.classification", value)} />
        <SelectInput label="Contains BCSI" value={String(Boolean(definition.security.contains_bcsi))} options={["true", "false"]} onChange={(value) => setField("security.contains_bcsi", value === "true")} />
        <SelectInput label="Contains PII" value={String(Boolean(definition.security.contains_pii))} options={["true", "false"]} onChange={(value) => setField("security.contains_pii", value === "true")} />
        <SelectInput label="Encryption Required" value={String(Boolean(definition.security.encryption_required))} options={["true", "false"]} onChange={(value) => setField("security.encryption_required", value === "true")} />
        <SelectInput label="Masking Required" value={String(Boolean(definition.security.masking_required))} options={["true", "false"]} onChange={(value) => setField("security.masking_required", value === "true")} />
        <TextInput label="Retention Days" value={definition.security.raw_payload_retention_days || 30} onChange={(value) => setField("security.raw_payload_retention_days", Number(value) || 0)} />
        <TextInput label="Access Group" value={definition.security.access_group || ""} onChange={(value) => setField("security.access_group", value)} />
      </div>
    </Section>
  );
}

function TextInput({ label, value, onChange }) {
  return (
    <label>
      {label}
      <input value={value ?? ""} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function TextArea({ label, value, onChange }) {
  return (
    <label className="field-full">
      {label}
      <textarea value={value ?? ""} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SelectInput({ label, value, options, onChange }) {
  return (
    <label>
      {label}
      <select value={value ?? ""} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function updatePath(object, path, value) {
  const keys = path.split(".");
  const next = structuredClone(object);
  let cursor = next;
  keys.slice(0, -1).forEach((key) => {
    cursor[key] = cursor[key] || {};
    cursor = cursor[key];
  });
  cursor[keys[keys.length - 1]] = value;
  return next;
}

function csvToArray(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function arrayToCsv(value) {
  return Array.isArray(value) ? value.join(",") : value || "";
}

function sanitizeDefinition(definition) {
  return {
    ...definition,
    columns: definition.columns.filter((column) => column.column_name.trim()),
  };
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
