export type MappingStatus = "Active" | "Draft" | "Issue";
export type MappingStatusFilter = "All" | MappingStatus;

export interface DataMappingStats {
  total: number;
  active: number;
  issues: number;
  fieldsMapped: number;
}

export interface DataMappingRule {
  id: string;
  name: string;
  sourceSystem: string;
  sourceObject: string;
  targetSystem: string;
  targetObject: string;
  fields: number;
  status: MappingStatus;
  owner: string;
  lastUpdated: string;
  validationScore: number;
}

export interface SchemaHealth {
  id: string;
  system: string;
  object: string;
  coverage: number;
  drift: number;
  lastScan: string;
  status: "Healthy" | "Warning" | "Critical";
}

export interface FieldTypeBucket {
  label: string;
  count: number;
  color: string;
}
