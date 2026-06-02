"use client";

import React, { useRef, useState } from "react";
import { Badge } from "@/components/ui/badge";

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TableColumn<T> {
  name: string;
  key: keyof T | "actions";
}

interface TableComponentsProps<T extends Record<string, unknown> & { id: string }> {
  data: T[];
  columns: TableColumn<T>[];
  onRowCheckboxChange?: (id: string, checked: boolean) => void;
  renderActionButtons?: (row: T) => React.ReactNode;
  emptyMessage?: string;
}

// ─── Status → Badge variant map (handles both PascalCase & lowercase) ─────────

const STATUS_BADGE_MAP: Record<string, "running" | "success" | "failed"> = {
  Running: "running",
  Success: "success",
  Failed: "failed",
  running: "running",
  success: "success",
  failed: "failed",
};

// ─── Indeterminate checkbox ───────────────────────────────────────────────────

function IndeterminateCheckbox({
  checked,
  indeterminate,
  onChange,
}: {
  checked: boolean;
  indeterminate: boolean;
  onChange: (checked: boolean) => void;
}) {
  const ref = useRef<HTMLInputElement>(null);

  React.useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate;
  }, [indeterminate]);

  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={(e) => onChange(e.target.checked)}
      className="h-4 w-4 cursor-pointer rounded border-gray-300 accent-primarygreen"
    />
  );
}

// ─── Table Component ──────────────────────────────────────────────────────────

function TableComponents<T extends Record<string, unknown> & { id: string }>({
  data,
  columns,
  onRowCheckboxChange,
  renderActionButtons,
  emptyMessage = "No data found.",
}: TableComponentsProps<T>) {
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set());

  const allSelected = data.length > 0 && selectedRows.size === data.length;
  const someSelected = selectedRows.size > 0 && selectedRows.size < data.length;

  const handleSelectAll = (checked: boolean) => {
    const next = checked ? new Set(data.map((row) => row.id)) : new Set<string>();
    setSelectedRows(next);
    data.forEach((row) => onRowCheckboxChange?.(row.id, checked));
  };

  const handleRowSelect = (id: string, checked: boolean) => {
    setSelectedRows((prev) => {
      const next = new Set(prev);
      if (checked) { next.add(id); } else { next.delete(id); }
      return next;
    });
    onRowCheckboxChange?.(id, checked);
  };

  const withCheckbox = Boolean(onRowCheckboxChange);

  // ── Empty state ─────────────────────────────────────────────────────────────
  if (data.length === 0) {
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-10 text-center text-sm text-gray-400">
        {emptyMessage}
      </div>
    );
  }

  // ── Table ───────────────────────────────────────────────────────────────────
  return (
    <div className="w-full overflow-x-auto rounded-lg border border-gray-200 bg-white">
      <table className="min-w-full divide-y divide-gray-200 text-left text-sm">

        {/* Head */}
        <thead className="bg-gray-50">
          <tr>
            {withCheckbox && (
              <th className="w-10 px-4 py-3">
                <IndeterminateCheckbox
                  checked={allSelected}
                  indeterminate={someSelected}
                  onChange={handleSelectAll}
                />
              </th>
            )}
            {columns.map((col) => (
              <th
                key={String(col.key)}
                className="whitespace-nowrap px-4 py-3 text-xs font-semibold uppercase tracking-wide text-gray-500"
              >
                {col.name}
              </th>
            ))}
          </tr>
        </thead>

        {/* Body */}
        <tbody className="divide-y divide-gray-100">
          {data.map((row) => {
            const isSelected = selectedRows.has(row.id);
            return (
              <tr
                key={row.id}
                className={`transition-colors duration-150 ${
                  isSelected ? "bg-green-50" : "hover:bg-gray-50"
                }`}
              >
                {withCheckbox && (
                  <td className="w-10 px-4 py-3">
                    <IndeterminateCheckbox
                      checked={isSelected}
                      indeterminate={false}
                      onChange={(checked) => handleRowSelect(row.id, checked)}
                    />
                  </td>
                )}

                {columns.map((col) => {
                  const key = col.key;

                  // Actions column
                  if (key === "actions") {
                    return (
                      <td key="actions" className="px-4 py-3">
                        {renderActionButtons?.(row)}
                      </td>
                    );
                  }

                  const value = row[key as keyof T];

                  // Status column — auto badge
                  if (key === "status" && typeof value === "string") {
                    const badgeVariant = STATUS_BADGE_MAP[value];
                    return (
                      <td key={String(key)} className="px-4 py-3">
                        <Badge variant={badgeVariant ?? "default"}>{value}</Badge>
                      </td>
                    );
                  }

                  // Default cell
                  return (
                    <td key={String(key)} className="whitespace-nowrap px-4 py-3 text-gray-700">
                      {value != null ? String(value) : "—"}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default TableComponents;
