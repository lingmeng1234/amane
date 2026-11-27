import {
  ActionIcon, Alert, Badge, Box, Button, Card, Group, Image, Pagination,
  SegmentedControl, SimpleGrid, Stack, Table, Text, TextInput, Title, Tooltip,
} from "@mantine/core";
import { IconRefresh, IconSearch, IconTrash, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { notifications } from "@mantine/notifications";
import { apiFetch } from "@/lib/api-token";
import { proxyImageUrl } from "@/lib/utils";

export const Route = createFileRoute("/uncollected-scenes/")({ component: UncollectedScenesPage });

type Gender = "female" | "transgender_female" | "male" | "unknown";
type Performer = { name: string; gender: Gender; official_gender?: Gender | null };
type SearchScene = {
  id: string; title: string; date: string; duration: number | null; studio: string;
  performers: Performer[]; tags: string[]; image: string | null;
};
type SavedScene = {
  id: number; theporndb_uuid: string; title: string; date: string; studio: string;
  performers: Performer[]; image_url: string | null; created_at: string;
};
type SceneList = { items: SavedScene[]; total: number; page: number; per_page: number };
type Filters = { query: string; performer: string; studio: string };

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

function genderSymbol(gender: Gender): string {
  if (gender === "female") return "♀";
  if (gender === "transgender_female") return "⚧";
  if (gender === "male") return "♂";
  return "?";
}

function genderName(gender: Gender): string {
  if (gender === "female") return "女性";
  if (gender === "transgender_female") return "跨性别女性";
  if (gender === "male") return "男性";
  return "未知性别";
}

function ActorText({ actor }: { actor: Performer }) {
  return (
    <Tooltip label={genderName(actor.gender)}>
      <Text size="sm" lineClamp={1} title={actor.name}>
        <Text span c="dimmed" fw={600} mr={4}>{genderSymbol(actor.gender)}</Text>
        {actor.name}
      </Text>
    </Tooltip>
  );
}

function SceneCard({ scene, onDelete }: { scene: SavedScene; onDelete: () => void }) {
  const actors = [...scene.performers];
  while (actors.length < 4) actors.push({ name: "—", gender: "unknown" });
  return (
    <Card withBorder padding="sm" radius="md" style={{ position: "relative" }}>
      <Box style={{ display: "grid", gridTemplateColumns: "144px minmax(0, 1fr)", gap: 12 }}>
        <Image
          src={scene.image_url ? proxyImageUrl(scene.image_url, "theporndb") : undefined}
          alt={scene.title} w={144} h={108} fit="cover" radius="sm" fallbackSrc=""
        />
        <Stack gap={3} style={{ minWidth: 0 }}>
          <Text fw={600} size="sm" lineClamp={1} title={scene.title}>{scene.title || "—"}</Text>
          <Text size="xs" c="dimmed">日期：{scene.date || "—"}</Text>
          <Text size="xs" c="dimmed" lineClamp={1} title={scene.studio}>制作商：{scene.studio || "—"}</Text>
          <Text size="xs" c="dimmed" lineClamp={1} title={scene.theporndb_uuid}>UUID：{scene.theporndb_uuid}</Text>
          <Box style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", columnGap: 10, rowGap: 3, paddingRight: 26 }}>
            {actors.map((actor, index) => (
              <Box key={index} style={{ minWidth: 0 }}>
                {actor.name === "—" ? <Text size="sm" c="dimmed">—</Text> : <ActorText actor={actor} />}
              </Box>
            ))}
          </Box>
        </Stack>
      </Box>
      <Tooltip label="从未收录名单移除">
        <ActionIcon
          color="red" variant="subtle" size="sm" aria-label="删除未收录记录" onClick={onDelete}
          style={{ position: "absolute", left: 151, top: 108, zIndex: 1 }}
        >
          <IconTrash size={16} />
        </ActionIcon>
      </Tooltip>
    </Card>
  );
}

function UncollectedScenesPage() {
  const queryClient = useQueryClient();
  const [studioInput, setStudioInput] = useState("");
  const [performerInput, setPerformerInput] = useState("");
  const [tagInput, setTagInput] = useState("");
  const [searchResults, setSearchResults] = useState<SearchScene[]>([]);
  const [searchError, setSearchError] = useState<string | null>(null);
  const emptyFilters: Filters = { query: "", performer: "", studio: "" };
  const [draft, setDraft] = useState<Filters>(emptyFilters);
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [page, setPage] = useState(1);
  const [view, setView] = useState<"cover" | "list">("cover");

  const listQuery = useQuery({
    queryKey: ["uncollected-scenes", page, filters],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), per_page: "30" });
      if (filters.query) params.set("query", filters.query);
      if (filters.performer) params.set("performer", filters.performer);
      if (filters.studio) params.set("studio", filters.studio);
      return requestJson<SceneList>("/api/uncollected-scenes?" + params.toString());
    },
  });

  const searchMutation = useMutation({
    mutationFn: () => requestJson<{ items: SearchScene[] }>("/api/theporndb-scenes/search", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ studio: studioInput.trim(), performer: performerInput.trim(), tag: tagInput.trim() }),
    }),
    onSuccess: (data) => { setSearchResults(data.items); setSearchError(null); },
    onError: (error) => setSearchError(error.message),
  });

  const addMutation = useMutation({
    mutationFn: (scene: SearchScene) => requestJson<{ added: boolean; already_collected: boolean }>(
      "/api/uncollected-scenes",
      {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          theporndb_uuid: scene.id, title: scene.title, date: scene.date, studio: scene.studio,
          performers: scene.performers.map((actor) => ({
            name: actor.name, official_gender: actor.official_gender ?? null,
          })),
          image_url: scene.image,
        }),
      },
    ),
    onSuccess: (result) => {
      notifications.show({
        message: result.already_collected ? "该作品已存在于片库，不会加入名单" : result.added ? "已加入未收录名单" : "该作品已在名单中",
        color: result.already_collected ? "yellow" : "blue",
      });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (uuid: string) => requestJson<{ deleted: boolean }>(
      "/api/uncollected-scenes/" + encodeURIComponent(uuid), { method: "DELETE" },
    ),
    onSuccess: () => {
      notifications.show({ message: "已从未收录名单移除", color: "blue" });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const refreshMutation = useMutation({
    mutationFn: () => requestJson<{ deleted: number }>("/api/uncollected-scenes/refresh", { method: "POST" }),
    onSuccess: (result) => {
      notifications.show({ message: "已清理 " + result.deleted + " 条已收录作品", color: "blue" });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const list = listQuery.data;
  const totalPages = Math.max(1, Math.ceil((list?.total ?? 0) / 30));
  const activeFilters = [
    filters.query ? { key: "query", label: "标题/UUID：" + filters.query } : null,
    filters.performer ? { key: "performer", label: "演员：" + filters.performer } : null,
    filters.studio ? { key: "studio", label: "厂牌：" + filters.studio } : null,
  ].filter((item): item is { key: string; label: string } => item !== null);

  function removeFilter(key: string) {
    const next = { ...filters, [key]: "" };
    setFilters(next);
    setDraft(next);
    setPage(1);
  }

  return (
    <Stack gap="lg">
      <Title order={2}>未收录影片</Title>
      <Card withBorder radius="md" padding="md">
        <Stack gap="sm">
          <Title order={4}>建档检索</Title>
          <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
            <TextInput label="厂牌" placeholder="输入 ThePornDB 厂牌名称" value={studioInput} onChange={(e) => setStudioInput(e.currentTarget.value)} />
            <TextInput label="演员" placeholder="展示名或别名，完全匹配" value={performerInput} onChange={(e) => setPerformerInput(e.currentTarget.value)} />
            <TextInput label="TAG" placeholder="输入 ThePornDB TAG，完全匹配" value={tagInput} onChange={(e) => setTagInput(e.currentTarget.value)} />
          </SimpleGrid>
          <Group justify="flex-end">
            <Button leftSection={<IconSearch size={16} />} loading={searchMutation.isPending}
              disabled={!studioInput.trim() && !performerInput.trim() && !tagInput.trim()}
              onClick={() => searchMutation.mutate()}>搜索</Button>
          </Group>
          {searchError && <Alert color="red">{searchError}</Alert>}
          {searchResults.length > 0 && (
            <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }} spacing="sm">
              {searchResults.map((scene) => (
                <Card key={scene.id} withBorder padding="xs" radius="sm">
                  <Group align="flex-start" wrap="nowrap">
                    <Image src={scene.image ? proxyImageUrl(scene.image, "theporndb") : undefined}
                      alt={scene.title} w={112} h={76} fit="cover" radius="sm" fallbackSrc="" />
                    <Stack gap={2} style={{ minWidth: 0, flex: 1 }}>
                      <Text size="sm" fw={600} lineClamp={2}>{scene.title || "—"}</Text>
                      <Text size="xs" c="dimmed">{scene.date || "—"} · {scene.studio || "—"}</Text>
                      <Text size="xs" c="dimmed" lineClamp={2}>
                        {scene.performers.map((actor) => genderSymbol(actor.gender) + " " + actor.name).join("、") || "—"}
                      </Text>
                      <Group gap={4} wrap="wrap">
                        {scene.tags.slice(0, 4).map((tag) => <Badge key={tag} size="xs" variant="light">{tag}</Badge>)}
                      </Group>
                    </Stack>
                  </Group>
                  <Group justify="flex-end" mt="xs">
                    <Button size="xs" variant="light" loading={addMutation.isPending && addMutation.variables?.id === scene.id}
                      disabled={addMutation.isPending} onClick={() => addMutation.mutate(scene)}>加入未收录名单</Button>
                  </Group>
                </Card>
              ))}
            </SimpleGrid>
          )}
          {searchMutation.isSuccess && searchResults.length === 0 && (
            <Text size="sm" c="dimmed" ta="center">没有找到匹配的场景</Text>
          )}
        </Stack>
      </Card>

      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Title order={4}>未收录名单（{list?.total ?? 0}）</Title>
          <Group gap="xs">
            <Button size="sm" variant="default" leftSection={<IconRefresh size={15} />}
              loading={refreshMutation.isPending} onClick={() => refreshMutation.mutate()}>刷新并清理已收录</Button>
            <SegmentedControl size="sm" value={view} onChange={(v) => setView(v as "cover" | "list")}
              data={[{ label: "封面", value: "cover" }, { label: "列表", value: "list" }]} />
          </Group>
        </Group>

        <Group align="end" gap="xs" wrap="wrap">
          <TextInput label="标题 / UUID" placeholder="搜索标题或 UUID" value={draft.query}
            onChange={(e) => setDraft({ ...draft, query: e.currentTarget.value })} style={{ flex: "1 1 180px" }} />
          <TextInput label="演员" placeholder="搜索演员" value={draft.performer}
            onChange={(e) => setDraft({ ...draft, performer: e.currentTarget.value })} style={{ flex: "1 1 160px" }} />
          <TextInput label="厂牌" placeholder="搜索厂牌" value={draft.studio}
            onChange={(e) => setDraft({ ...draft, studio: e.currentTarget.value })} style={{ flex: "1 1 160px" }} />
          <Button leftSection={<IconSearch size={15} />} onClick={() => { setFilters({ ...draft }); setPage(1); }}>筛选</Button>
          <Button variant="subtle" color="gray" onClick={() => { setDraft(emptyFilters); setFilters(emptyFilters); setPage(1); }}>清除</Button>
        </Group>

        {activeFilters.length > 0 && (
          <Group gap="xs">
            {activeFilters.map((filter) => (
              <Badge key={filter.key} variant="light" rightSection={
                <ActionIcon size="xs" variant="transparent" color="gray" aria-label="移除筛选" onClick={() => removeFilter(filter.key)}>
                  <IconX size={12} />
                </ActionIcon>
              }>{filter.label}</Badge>
            ))}
          </Group>
        )}

        {listQuery.isError && <Alert color="red">{(listQuery.error as Error).message}</Alert>}
        {listQuery.isLoading ? <Text size="sm" c="dimmed">加载中…</Text> :
          (list?.items.length ?? 0) === 0 ? <Text size="sm" c="dimmed" ta="center" py="xl">暂无未收录影片</Text> :
          view === "cover" ? (
            <SimpleGrid cols={{ base: 1, sm: 1, md: 2 }} spacing="sm">
              {list?.items.map((scene) => (
                <SceneCard key={scene.id} scene={scene} onDelete={() => deleteMutation.mutate(scene.theporndb_uuid)} />
              ))}
            </SimpleGrid>
          ) : (
            <Table.ScrollContainer minWidth={720}>
              <Table striped highlightOnHover withTableBorder>
                <Table.Thead><Table.Tr>
                  <Table.Th>标题</Table.Th><Table.Th>UUID</Table.Th><Table.Th>日期</Table.Th>
                  <Table.Th>厂牌</Table.Th><Table.Th>全部演员</Table.Th><Table.Th w={48}>操作</Table.Th>
                </Table.Tr></Table.Thead>
                <Table.Tbody>
                  {list?.items.map((scene) => (
                    <Table.Tr key={scene.id}>
                      <Table.Td>{scene.title || "—"}</Table.Td>
                      <Table.Td>{scene.theporndb_uuid}</Table.Td>
                      <Table.Td>{scene.date || "—"}</Table.Td>
                      <Table.Td>{scene.studio || "—"}</Table.Td>
                      <Table.Td>{scene.performers.map((actor) => genderSymbol(actor.gender) + " " + actor.name).join("、") || "—"}</Table.Td>
                      <Table.Td><ActionIcon color="red" variant="subtle" aria-label="删除"
                        onClick={() => deleteMutation.mutate(scene.theporndb_uuid)}><IconTrash size={16} /></ActionIcon></Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )
        }
        {totalPages > 1 && <Group justify="center"><Pagination total={totalPages} value={page} onChange={setPage} /></Group>}
      </Stack>
    </Stack>
  );
}
