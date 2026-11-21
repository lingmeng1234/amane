import {
  Alert,
  Button,
  Checkbox,
  Group,
  Paper,
  Pagination,
  Select,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useRef, useState } from "react";
import { apiFetch } from "@/lib/api-token";

export const Route = createFileRoute("/dmm-mappings")({ component: DmmMappingsPage });
type Entry = { source: string; target: string };
type Conflict = {
  group_id: number;
  reason: "source";
  old?: Entry;
  new?: Entry;
};
const emptyEntry = (): Entry => ({ source: "", target: "" });
function errorText(error: unknown): string {
  const raw = error instanceof Error ? error.message : String(error);
  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };
    if (typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* plain text */
  }
  return raw.replace(/^Error: /, "");
}
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) throw new Error(await response.text());
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

function DmmMappingsPage() {
  const qc = useQueryClient();
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [draft, setDraft] = useState<Entry>(emptyEntry());
  const [editingSource, setEditingSource] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<Entry>(emptyEntry());
  const [message, setMessage] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<Conflict[]>([]);
  const [conflictSearch, setConflictSearch] = useState("");
  const [conflictPage, setConflictPage] = useState(1);
  const [conflictDrafts, setConflictDrafts] = useState<Record<string, Entry>>({});
  const [selected, setSelected] = useState<string[]>([]);
  const [mode, setMode] = useState<"merge" | "replace">("merge");
  const jsonRef = useRef<HTMLInputElement>(null);
  const pageSize = 30;
  const conflictPageSize = 10;
  const query = useQuery({
    queryKey: ["dmm-mappings", search, page],
    queryFn: () =>
      request<{ items: Entry[]; total: number }>(
        `/api/dmm-mappings?search=${encodeURIComponent(search)}&limit=${pageSize}&offset=${(page - 1) * pageSize}`,
      ),
  });
  useEffect(() => {
    void request<Conflict[]>("/api/dmm-mappings/exceptions")
      .then(setConflicts)
      .catch((error) => setMessage(`冲突列表读取失败：${errorText(error)}`));
  }, []);
  useEffect(() => {
    if (!message) return;
    const timer = window.setTimeout(() => setMessage(null), 5000);
    return () => window.clearTimeout(timer);
  }, [message]);
  const pageCount = Math.max(1, Math.ceil((query.data?.total ?? 0) / pageSize));
  const visibleItems = query.data?.items ?? [];
  const visibleSources = visibleItems.map((item) => item.source);
  const allVisibleSelected = visibleSources.length > 0 && visibleSources.every((source) => selected.includes(source));
  const someVisibleSelected = visibleSources.some((source) => selected.includes(source));
  const filteredConflicts = conflicts.filter((item) =>
    !conflictSearch.trim()
      ? true
      : [item.old?.source ?? "", item.old?.target ?? "", item.new?.source ?? "", item.new?.target ?? ""].some(
          (value) => value === conflictSearch.trim(),
        ),
  );
  const conflictPageCount = Math.max(1, Math.ceil(filteredConflicts.length / conflictPageSize));
  const visibleConflicts = filteredConflicts.slice(
    (conflictPage - 1) * conflictPageSize,
    conflictPage * conflictPageSize,
  );
  const conflictCount = conflicts.reduce(
    (sum, item) => sum + Number(Boolean(item.old)) + Number(Boolean(item.new)),
    0,
  );
  const refresh = () => void qc.invalidateQueries({ queryKey: ["dmm-mappings"] });
  const saveNew = useMutation({
    mutationFn: () =>
      request<Entry>("/api/dmm-mappings", {
        method: "PUT",
        body: JSON.stringify(draft),
      }),
    onSuccess: () => {
      setDraft(emptyEntry());
      setMessage("新增 DMM和谐映射成功");
      refresh();
    },
    onError: (error) => setMessage(`新增失败：${errorText(error)}`),
  });
  const saveEdit = useMutation({
    mutationFn: (entry: Entry) =>
      request<Entry>("/api/dmm-mappings", {
        method: "PUT",
        body: JSON.stringify({ ...entry, original_source: editingSource }),
      }),
    onSuccess: () => {
      setEditingSource(null);
      setEditDraft(emptyEntry());
      setMessage("DMM和谐映射修改已保存");
      refresh();
    },
    onError: (error) => setMessage(`保存失败：${errorText(error)}`),
  });
  const remove = useMutation({
    mutationFn: (source: string) =>
      request(`/api/dmm-mappings/item?source=${encodeURIComponent(source)}`, { method: "DELETE" }),
    onSuccess: () => {
      setMessage("映射已删除");
      refresh();
    },
    onError: (error) => setMessage(`删除失败：${errorText(error)}`),
  });
  const batchRemove = useMutation({
    mutationFn: () =>
      request<{ deleted: number }>("/api/dmm-mappings/batch-delete", {
        method: "POST",
        body: JSON.stringify({ sources: selected }),
      }),
    onSuccess: (result) => {
      setMessage(`已删除 ${result.deleted} 条映射`);
      setSelected([]);
      refresh();
    },
    onError: (error) => setMessage(`批量删除失败：${errorText(error)}`),
  });
  const saveConflict = useMutation({
    mutationFn: (payload: { entry: Entry; group_id: number; side: "old" | "new" }) =>
      request<Conflict[]>("/api/dmm-mappings/exceptions/save", {
        method: "POST",
        body: JSON.stringify(payload),
      }),
    onSuccess: (items) => {
      setConflicts(items);
      setConflictDrafts({});
      setMessage("冲突记录已保存并加入正式映射");
      refresh();
    },
    onError: (error) => setMessage(`冲突记录保存失败：${errorText(error)}`),
  });
  async function reloadConflicts() {
    setConflicts(await request<Conflict[]>("/api/dmm-mappings/exceptions"));
  }
  async function importJson(file: File) {
    try {
      const raw = await file.text();
      const result = await request<{ added?: string[]; unchanged?: string[]; conflicts?: Conflict[]; replaced?: number }>(
        `/api/dmm-mappings/import?mode=${mode}`,
        { method: "POST", body: raw },
      );
      await reloadConflicts();
      setConflictPage(1);
      setSelected([]);
      if (mode === "replace") {
        setMessage(`整体替换完成，共 ${result.replaced ?? 0} 条映射`);
      } else {
        setMessage(
          `新增 ${result.added?.length ?? 0} 条；未变化 ${result.unchanged?.length ?? 0} 条；冲突 ${result.conflicts?.length ?? 0} 组`,
        );
      }
      refresh();
    } catch (error) {
      setMessage(`JSON 导入失败：${errorText(error)}`);
    }
  }
  function updateConflictDraft(groupId: number, side: "old" | "new", entry: Entry, patch: Partial<Entry>) {
    const key = `${groupId}:${side}`;
    setConflictDrafts((current) => ({
      ...current,
      [key]: { ...(current[key] ?? entry), ...patch },
    }));
  }
  async function deleteConflict(groupId: number, side: "old" | "new") {
    try {
      const items = await request<Conflict[]>("/api/dmm-mappings/exceptions", {
        method: "PUT",
        body: JSON.stringify({ group_id: groupId, side, entry: null }),
      });
      setConflicts(items);
      setConflictDrafts((current) => {
        const next = { ...current };
        delete next[`${groupId}:${side}`];
        return next;
      });
    } catch (error) {
      setMessage(`冲突记录删除失败：${errorText(error)}`);
    }
  }

  return (
    <Stack gap="md" pb={100}>
      <div>
        <Title order={2}>DMM和谐映射表</Title>
        <Text c="dimmed" size="sm">
          将 DMM 标题、剧情中的和谐词替换为修正文字；原和谐词必须唯一，修正后的文字允许重复。搜索按原和谐词或修正后文字完整精确匹配。
        </Text>
      </div>
      <Paper p="md" withBorder>
        <Stack gap="sm">
          <Group grow align="end">
            <TextInput
              label="映射词搜索"
              placeholder="输入完整的原和谐词或修正后文字（精确匹配）"
              value={search}
              onChange={(event) => {
                setSearch(event.currentTarget.value);
                setPage(1);
                setSelected([]);
              }}
            />
            <Text size="sm" c="dimmed">
              共 {query.data?.total ?? 0} 条
            </Text>
          </Group>
          <Group align="end">
            <Select
              aria-label="导入模式"
              value={mode}
              onChange={(value) => value && setMode(value as "merge" | "replace")}
              data={[
                { value: "merge", label: "合并导入" },
                { value: "replace", label: "整体替换" },
              ]}
              w={130}
            />
            <Button
              color={mode === "replace" ? "orange" : "blue"}
              variant="light"
              onClick={() => {
                if (mode === "replace" && !window.confirm("整体替换会覆盖全部 DMM和谐映射，确定继续？")) return;
                jsonRef.current?.click();
              }}
            >
              JSON 导入
            </Button>
            <input
              ref={jsonRef}
              hidden
              type="file"
              accept=".json,application/json"
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                if (file) void importJson(file);
                event.currentTarget.value = "";
              }}
            />
            <Button component="a" variant="light" href="/api/dmm-mappings/export">
              JSON 导出
            </Button>
          </Group>
        </Stack>
      </Paper>
      {message && <Alert>{message}</Alert>}
      <Paper p="md" withBorder>
        <Stack gap="sm">
          <Title order={4}>新增映射</Title>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr) auto",
              gap: "var(--mantine-spacing-sm)",
              alignItems: "end",
            }}
          >
            <TextInput
              label="原和谐词"
              placeholder="例如：催O"
              value={draft.source}
              onChange={(event) => setDraft({ ...draft, source: event.currentTarget.value })}
            />
            <TextInput
              label="修正后文字"
              placeholder="例如：催眠"
              value={draft.target}
              onChange={(event) => setDraft({ ...draft, target: event.currentTarget.value })}
            />
            <Button
              loading={saveNew.isPending}
              disabled={!draft.source.trim() || !draft.target.trim()}
              onClick={() => saveNew.mutate()}
            >
              新增
            </Button>
          </div>
        </Stack>
      </Paper>
      <Tabs defaultValue="existing" keepMounted={false}>
        <Tabs.List>
          <Tabs.Tab value="existing">现有映射</Tabs.Tab>
          <Tabs.Tab value="conflicts">映射冲突复查（{conflictCount}）</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="existing" pt="md">
          <Paper p="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={4}>现有 DMM和谐映射</Title>
                <Group>
                  <Text size="sm">已选 {selected.length} 条</Text>
                  <Button
                    size="xs"
                    color="red"
                    variant="light"
                    disabled={selected.length === 0}
                    loading={batchRemove.isPending}
                    onClick={() => {
                      if (selected.length > 0 && window.confirm(`确定删除选中的 ${selected.length} 条映射？`)) {
                        batchRemove.mutate();
                      }
                    }}
                  >
                    批量删除
                  </Button>
                </Group>
              </Group>
              {query.isLoading ? (
                <Text>加载中…</Text>
              ) : (
                <Table.ScrollContainer minWidth={560}>
                  <Table striped highlightOnHover>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th w={44}>
                          <Checkbox
                            aria-label="选择当前页"
                            checked={Boolean(allVisibleSelected)}
                            indeterminate={Boolean(someVisibleSelected && !allVisibleSelected)}
                            onChange={(event) => {
                              const checked = event.currentTarget.checked;
                              setSelected((current) =>
                                checked
                                  ? [...new Set([...current, ...visibleSources])]
                                  : current.filter((source) => !visibleSources.includes(source)),
                              );
                            }}
                          />
                        </Table.Th>
                        <Table.Th>原和谐词</Table.Th>
                        <Table.Th>修正后文字</Table.Th>
                        <Table.Th w={150}>操作</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {visibleItems.map((entry) => (
                        <Table.Tr key={entry.source}>
                          <Table.Td>
                            <Checkbox
                              checked={Boolean(selected.includes(entry.source))}
                              onChange={(event) => {
                                const checked = event.currentTarget.checked;
                                setSelected((current) =>
                                  checked
                                    ? current.includes(entry.source)
                                      ? current
                                      : [...current, entry.source]
                                    : current.filter((source) => source !== entry.source),
                                );
                              }}
                            />
                          </Table.Td>
                          {editingSource === entry.source ? (
                            <>
                              <Table.Td>
                                <TextInput
                                  size="xs"
                                  value={editDraft.source}
                                  onChange={(event) => setEditDraft({ ...editDraft, source: event.currentTarget.value })}
                                />
                              </Table.Td>
                              <Table.Td>
                                <TextInput
                                  size="xs"
                                  value={editDraft.target}
                                  onChange={(event) => setEditDraft({ ...editDraft, target: event.currentTarget.value })}
                                />
                              </Table.Td>
                              <Table.Td>
                                <Group gap="xs" wrap="nowrap">
                                  <Button
                                    size="xs"
                                    loading={saveEdit.isPending}
                                    disabled={!editDraft.source.trim() || !editDraft.target.trim()}
                                    onClick={() => saveEdit.mutate(editDraft)}
                                  >
                                    保存
                                  </Button>
                                  <Button size="xs" variant="default" onClick={() => setEditingSource(null)}>
                                    取消
                                  </Button>
                                </Group>
                              </Table.Td>
                            </>
                          ) : (
                            <>
                              <Table.Td>{entry.source}</Table.Td>
                              <Table.Td>{entry.target}</Table.Td>
                              <Table.Td>
                                <Group gap="xs" wrap="nowrap">
                                  <Button
                                    size="xs"
                                    variant="light"
                                    onClick={() => {
                                      setEditingSource(entry.source);
                                      setEditDraft({ ...entry });
                                    }}
                                  >
                                    编辑
                                  </Button>
                                  <Button
                                    size="xs"
                                    color="red"
                                    variant="subtle"
                                    onClick={() => remove.mutate(entry.source)}
                                  >
                                    删除
                                  </Button>
                                </Group>
                              </Table.Td>
                            </>
                          )}
                        </Table.Tr>
                      ))}
                    </Table.Tbody>
                  </Table>
                </Table.ScrollContainer>
              )}
              <Group justify="space-between">
                <Text size="sm">每页 30 条；当前第 {page} / {pageCount} 页</Text>
                <Pagination
                  total={pageCount}
                  value={page}
                  onChange={(value) => {
                    setPage(value);
                    setSelected([]);
                  }}
                />
              </Group>
            </Stack>
          </Paper>
        </Tabs.Panel>
        <Tabs.Panel value="conflicts" pt="md">
          <Paper p="md" withBorder>
            <Stack gap="sm">
              <Group justify="space-between">
                <Title order={4}>映射冲突复查（{conflictCount} 条）</Title>
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  disabled={conflicts.length === 0}
                  onClick={() => {
                    void request("/api/dmm-mappings/exceptions/clear", { method: "POST" })
                      .then(() => {
                        setConflicts([]);
                        setConflictDrafts({});
                      })
                      .catch((error) => setMessage(`清空冲突列表失败：${errorText(error)}`));
                  }}
                >
                  清空冲突列表
                </Button>
              </Group>
              <TextInput
                placeholder="精确搜索原和谐词或修正后文字"
                value={conflictSearch}
                onChange={(event) => {
                  setConflictSearch(event.currentTarget.value);
                  setConflictPage(1);
                }}
              />
              <Text size="sm" c="dimmed">
                合并导入时，若原和谐词已存在但修正结果不同，会将原记录和导入记录一起移入冲突区，不影响其他不冲突映射。选择需要保留的一条，编辑后保存并加入正式映射；另一条可单独删除。
              </Text>
              {visibleConflicts.length === 0 ? (
                <Text c="dimmed" size="sm">暂无待复查冲突</Text>
              ) : (
                visibleConflicts.map((item) => (
                  <Paper key={item.group_id} p="sm" withBorder>
                    <Stack gap="sm">
                      <Text fw={700}>冲突组 #{item.group_id} · 原和谐词重复</Text>
                      {(["old", "new"] as const).map((side) => {
                        const entry = item[side];
                        if (!entry) return null;
                        const key = `${item.group_id}:${side}`;
                        const draftEntry = conflictDrafts[key] ?? entry;
                        return (
                          <Paper key={side} p="sm" withBorder>
                            <Stack gap="xs">
                              <Text fw={600}>{side === "old" ? "原有映射" : "导入映射"}</Text>
                              <div
                                style={{
                                  display: "grid",
                                  gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1fr)",
                                  gap: 8,
                                }}
                              >
                                <TextInput
                                  size="sm"
                                  label="原和谐词"
                                  value={draftEntry.source}
                                  onChange={(event) => updateConflictDraft(item.group_id, side, entry, { source: event.currentTarget.value })}
                                />
                                <TextInput
                                  size="sm"
                                  label="修正后文字"
                                  value={draftEntry.target}
                                  onChange={(event) => updateConflictDraft(item.group_id, side, entry, { target: event.currentTarget.value })}
                                />
                              </div>
                              <Group justify="flex-end">
                                <Button
                                  size="xs"
                                  loading={saveConflict.isPending}
                                  disabled={!draftEntry.source.trim() || !draftEntry.target.trim()}
                                  onClick={() => saveConflict.mutate({ entry: draftEntry, group_id: item.group_id, side })}
                                >
                                  保存并加入映射
                                </Button>
                                <Button size="xs" color="red" variant="light" onClick={() => void deleteConflict(item.group_id, side)}>
                                  删除此项
                                </Button>
                              </Group>
                            </Stack>
                          </Paper>
                        );
                      })}
                    </Stack>
                  </Paper>
                ))
              )}
              <Group justify="space-between">
                <Text size="xs" c="dimmed">共 {filteredConflicts.length} 组冲突</Text>
                <Pagination size="sm" total={conflictPageCount} value={conflictPage} onChange={setConflictPage} />
              </Group>
            </Stack>
          </Paper>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}
