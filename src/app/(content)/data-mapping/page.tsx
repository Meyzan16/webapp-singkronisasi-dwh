"use client";

import { useMemo, useState } from "react";
import { GitBranchPlus, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MappingStatusFilter } from "@/types/data-mapping";
import FieldTypeBreakdown from "@/features/data-mapping/components/field-type-breakdown";
import MappingFilterBar from "@/features/data-mapping/components/mapping-filter-bar";
import MappingStatsCards from "@/features/data-mapping/components/mapping-stats-cards";
import MappingTable from "@/features/data-mapping/components/mapping-table";
import SchemaHealthPanel from "@/features/data-mapping/components/schema-health-panel";
import {
  dataMappingRules,
  dataMappingStats,
  fieldTypeBuckets,
  schemaHealth,
} from "@/features/data-mapping/data/mock-data";

export default function DataMappingPage() {
  const [statusFilter, setStatusFilter] = useState<MappingStatusFilter>("All");
  const [sourceFilter, setSourceFilter] = useState("All");
  const [searchQuery, setSearchQuery] = useState("");

  const sourceOptions = useMemo(
    () => Array.from(new Set(dataMappingRules.map((rule) => rule.sourceSystem))),
    [],
  );

  const filteredMappings = useMemo(() => {
    const query = searchQuery.toLowerCase();

    return dataMappingRules.filter((rule) => {
      const statusMatch = statusFilter === "All" || rule.status === statusFilter;
      const sourceMatch = sourceFilter === "All" || rule.sourceSystem === sourceFilter;
      const searchMatch =
        rule.id.toLowerCase().includes(query) ||
        rule.name.toLowerCase().includes(query) ||
        rule.sourceObject.toLowerCase().includes(query) ||
        rule.targetObject.toLowerCase().includes(query);

      return statusMatch && sourceMatch && searchMatch;
    });
  }, [searchQuery, sourceFilter, statusFilter]);

  const handleReset = () => {
    setStatusFilter("All");
    setSourceFilter("All");
    setSearchQuery("");
  };

  return (
    <main className="space-y-4 pb-8">
      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button variant="outline" size="sm" className="rounded-md">
          <ShieldCheck size={14} />
          Validate Rules
        </Button>
        <Button variant="primary" size="sm" className="rounded-md">
          <GitBranchPlus size={14} />
          Add Mapping
        </Button>
      </div>

      <MappingStatsCards stats={dataMappingStats} />

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[1.55fr_1fr]">
        <FieldTypeBreakdown buckets={fieldTypeBuckets} />
        <SchemaHealthPanel schemas={schemaHealth} />
      </div>

      <MappingFilterBar
        activeStatus={statusFilter}
        onStatusChange={setStatusFilter}
        source={sourceFilter}
        onSourceChange={setSourceFilter}
        sourceOptions={sourceOptions}
        search={searchQuery}
        onSearchChange={setSearchQuery}
        onReset={handleReset}
      />

      <MappingTable mappings={filteredMappings} />
    </main>
  );
}
