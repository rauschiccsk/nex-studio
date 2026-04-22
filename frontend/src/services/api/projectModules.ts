import api from "../api";
import type { PaginatedResponse } from "../../types";
import type { ProjectModuleCreate, ProjectModuleRead, ProjectModuleUpdate } from "../../types/projectModule";
import type { ModuleDependencyCreate, ModuleDependencyRead } from "../../types/moduleDependency";

// ─── Project Modules ──────────────────────────────────────────────────────────

export interface ListModulesParams {
  project_id?: string;
  status?: string;
  category?: string;
  skip?: number;
  limit?: number;
  [key: string]: string | number | boolean | null | undefined;
}

export function listProjectModules(
  params: ListModulesParams = {},
): Promise<PaginatedResponse<ProjectModuleRead>> {
  return api.get<PaginatedResponse<ProjectModuleRead>>("/project-modules", { params });
}

export function getProjectModule(moduleId: string): Promise<ProjectModuleRead> {
  return api.get<ProjectModuleRead>(`/project-modules/${moduleId}`);
}

export function createProjectModule(data: ProjectModuleCreate): Promise<ProjectModuleRead> {
  return api.post<ProjectModuleRead>("/project-modules", data);
}

export function updateProjectModule(
  moduleId: string,
  data: ProjectModuleUpdate,
): Promise<ProjectModuleRead> {
  return api.patch<ProjectModuleRead>(`/project-modules/${moduleId}`, data);
}

export function deleteProjectModule(moduleId: string): Promise<void> {
  return api.delete<void>(`/project-modules/${moduleId}`);
}

// ─── Module Dependencies ──────────────────────────────────────────────────────

export interface ListDepsParams {
  module_id?: string;
  depends_on_module_id?: string;
  skip?: number;
  limit?: number;
  [key: string]: string | number | boolean | null | undefined;
}

export function listModuleDependencies(
  params: ListDepsParams = {},
): Promise<PaginatedResponse<ModuleDependencyRead>> {
  return api.get<PaginatedResponse<ModuleDependencyRead>>("/module-dependencies", { params });
}

export function createModuleDependency(data: ModuleDependencyCreate): Promise<ModuleDependencyRead> {
  return api.post<ModuleDependencyRead>("/module-dependencies", data);
}

export function deleteModuleDependency(dependencyId: string): Promise<void> {
  return api.delete<void>(`/module-dependencies/${dependencyId}`);
}
