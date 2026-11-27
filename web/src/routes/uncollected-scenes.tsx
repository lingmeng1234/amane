import {
  ActionIcon,
  AspectRatio,
  Badge,
  Box,
  Button,
  Card,
  Collapse,
  Group,
  Image,
  Pagination,
  Select,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
  Title,
  Tooltip,
} from "@mantine/core";
import { IconFilter, IconRefresh, IconTrash, IconX } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { notifications } from "@mantine/notifications";
import type { ActorGender } from "@/client/types.gen";
import { FacetBadge } from "@/components/media/facet-badge";
import { apiFetch } from "@/lib/api-token";
import { proxyImageUrl } from "@/lib/utils";

export const Route = createFileRoute("/uncollected-scenes")({
  component: UncollectedScenesPage,
});

type Performer = {
  name: string;
  gender: ActorGender;
  official_gender?: ActorGender | null;
};

type SavedScene = {
  id: number;
  theporndb_uuid: string;
  title: string;
  date: string;
  studio: string;
  performers: Performer[];
  image_url: string | null;
  created_at: string;
};

type SceneList = {
  items: SavedScene[];
  total: number;
  page: number;
  per_page: number;
};

type SceneFacets = {
  performers: string[];
  studios: string[];
};

type Filters = {
  performer: string;
  studio: string;
};

type BuildResult = {
  matched: number;
  added: number;
  already_in_list: number;
  already_collected: number;
};

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await apiFetch(url, init);
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail ?? response.statusText);
  }
  return (await response.json()) as T;
}

function SceneCard({ scene, onDelete }: { scene: SavedScene; onDelete: () => void }) {
  const actors = [...scene.performers];
  while (actors.length < 4) actors.push({ name: "—", gender: "unknown" });

  return (
    <Card withBorder padding="sm" radius="md" style={{ position: "relative" }}>
      <Box pos="relative">
        <AspectRatio ratio={1.5}>
          <Box
            bg="var(--mantine-color-default-hover)"
            style={{ overflow: "hidden", borderRadius: "var(--mantine-radius-sm)" }}
          >
            <Image
              src={scene.image_url ? proxyImageUrl(scene.image_url, "theporndb") : undefined}
              alt={scene.title}
              w="100%"
              h="100%"
              fit="contain"
              fallbackSrc=""
            />
          </Box>
        </AspectRatio>
        <Tooltip label="从未收录名单移除">
          <ActionIcon
            color="red"
            variant="filled"
            size="sm"
            aria-label="删除未收录记录"
            onClick={onDelete}
            style={{ position: "absolute", right: 8, bottom: 8, zIndex: 1 }}
          >
            <IconTrash size={15} />
          </ActionIcon>
        </Tooltip>
      </Box>

      <Stack gap={4} mt="sm" style={{ minWidth: 0 }}>
        <Text fw={600} size="sm" lineClamp={2} title={scene.title}>
          {scene.title || "—"}
        </Text>
        <Text size="xs" c="dimmed">
          日期：{scene.date || "—"}
        </Text>
        <Text size="xs" c="dimmed" lineClamp={1} title={scene.studio}>
          制作商：{scene.studio || "—"}
        </Text>
        <Text size="xs" c="dimmed" lineClamp={1} title={scene.theporndb_uuid}>
          UUID：{scene.theporndb_uuid}
        </Text>
        <Box
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            columnGap: 8,
            rowGap: 5,
            paddingRight: 4,
          }}
        >
          {actors.map((actor, index) => (
            <Box key={index} style={{ minWidth: 0, overflow: "hidden" }}>
              {actor.name === "—" ? (
                <Text size="sm" c="dimmed">—</Text>
              ) : (
                <FacetBadge
                  kind="actor"
                  id={null}
                  name={actor.name}
                  gender={actor.gender}
                  size="sm"
                  variant="light"
                />
              )}
            </Box>
          ))}
        </Box>
      </Stack>
    </Card>
  );
}

function UncollectedScenesPage() {
  const queryClient = useQueryClient();
  const [studioInput, setStudioInput] = useState("");
  const [performerInput, setPerformerInput] = useState("");
  const [tagInput, setTagInput] = useState("");
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [performerOptionQuery, setPerformerOptionQuery] = useState("");
  const [studioOptionQuery, setStudioOptionQuery] = useState("");
  const [filters, setFilters] = useState<Filters>({ performer: "", studio: "" });
  const [page, setPage] = useState(1);

  const listQuery = useQuery({
    queryKey: ["uncollected-scenes", page, filters],
    queryFn: () => {
      const params = new URLSearchParams({ page: String(page), per_page: "30" });
      if (filters.performer) params.set("performer", filters.performer);
      if (filters.studio) params.set("studio", filters.studio);
      return requestJson<SceneList>("/api/uncollected-scenes?" + params.toString());
    },
  });

  const facetsQuery = useQuery({
    queryKey: ["uncollected-scene-facets"],
    queryFn: () => requestJson<SceneFacets>("/api/uncollected-scenes/facets"),
  });

  const buildMutation = useMutation({
    mutationFn: () =>
      requestJson<BuildResult>("/api/theporndb-scenes/build-uncollected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          studio: studioInput.trim(),
          performer: performerInput.trim(),
          tag: tagInput.trim(),
        }),
      }),
    onSuccess: (result) => {
      notifications.show({
        color: "blue",
        message:
          `建档完成：命中 ${result.matched} 条，新增 ${result.added} 条，名单重复 ${result.already_in_list} 条，片库已有 ${result.already_collected} 条`,
      });
      setPage(1);
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-facets"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-status"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const deleteMutation = useMutation({
    mutationFn: (uuid: string) =>
      requestJson<{ deleted: boolean }>("/api/uncollected-scenes/" + encodeURIComponent(uuid), {
        method: "DELETE",
      }),
    onSuccess: () => {
      notifications.show({ message: "已从未收录名单移除", color: "blue" });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-facets"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-status"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const refreshMutation = useMutation({
    mutationFn: () =>
      requestJson<{ deleted: number }>("/api/uncollected-scenes/refresh", { method: "POST" }),
    onSuccess: (result) => {
      notifications.show({ message: "已清理 " + result.deleted + " 条已收录作品", color: "blue" });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scenes"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-facets"] });
      void queryClient.invalidateQueries({ queryKey: ["uncollected-scene-status"] });
    },
    onError: (error) => notifications.show({ message: error.message, color: "red" }),
  });

  const list = listQuery.data;
  const totalPages = Math.max(1, Math.ceil((list?.total ?? 0) / 30));
  const performerOptions = useMemo(
    () =>
      (facetsQuery.data?.performers ?? [])
        .filter((name) => name.toLocaleLowerCase().includes(performerOptionQuery.trim().toLocaleLowerCase()))
        .map((name) => ({ value: name, label: name })),
    [facetsQuery.data?.performers, performerOptionQuery],
  );
  const studioOptions = useMemo(
    () =>
      (facetsQuery.data?.studios ?? [])
        .filter((name) => name.toLocaleLowerCase().includes(studioOptionQuery.trim().toLocaleLowerCase()))
        .map((name) => ({ value: name, label: name })),
    [facetsQuery.data?.studios, studioOptionQuery],
  );
  const activeFilters = [
    filters.performer ? { key: "performer" as const, label: "演员：" + filters.performer } : null,
    filters.studio ? { key: "studio" as const, label: "制作商：" + filters.studio } : null,
  ].filter((item): item is { key: "performer" | "studio"; label: string } => item !== null);

  function updateFilter(key: keyof Filters, value: string | null) {
    setFilters((current) => ({ ...current, [key]: value ?? "" }));
    setPage(1);
  }

  function removeFilter(key: keyof Filters) {
    setFilters((current) => ({ ...current, [key]: "" }));
    setPage(1);
  }

  return (
    <Stack gap="md">
      <Title order={2}>未收录影片</Title>

      <Card withBorder radius="md" padding="md">
        <Stack gap="sm">
          <Title order={4}>建档检索</Title>
          <Group grow align="end" wrap="nowrap">
            <TextInput
              label="制作商"
              placeholder="输入 ThePornDB 制作商名称"
              value={studioInput}
              onChange={(event) => setStudioInput(event.currentTarget.value)}
            />
            <TextInput
              label="演员"
              placeholder="展示名或别名，完全匹配"
              value={performerInput}
              onChange={(event) => setPerformerInput(event.currentTarget.value)}
            />
            <TextInput
              label="TAG"
              placeholder="输入 ThePornDB TAG，完全匹配"
              value={tagInput}
              onChange={(event) => setTagInput(event.currentTarget.value)}
            />
          </Group>
          <Group justify="flex-end">
            <Button
              loading={buildMutation.isPending}
              disabled={!studioInput.trim() && !performerInput.trim() && !tagInput.trim()}
              onClick={() => buildMutation.mutate()}
            >
              建档
            </Button>
          </Group>
        </Stack>
      </Card>

      <Stack gap="sm">
        <Group justify="space-between" align="center">
          <Box>
            <Title order={4}>未收录名单</Title>
            <Text size="xs" c="dimmed">
              当前显示 {list?.items.length ?? 0} / 全部 {list?.total ?? 0} 条
            </Text>
          </Box>
          <Button
            size="sm"
            variant="default"
            leftSection={<IconRefresh size={15} />}
            loading={refreshMutation.isPending}
            onClick={() => refreshMutation.mutate()}
          >
            刷新并清理已收录
          </Button>
        </Group>

        <Group gap="xs" align="end" wrap="nowrap">
          <TextInput
            size="sm"
            placeholder="搜索演员选项"
            aria-label="搜索演员筛选选项"
            value={performerOptionQuery}
            onChange={(event) => setPerformerOptionQuery(event.currentTarget.value)}
            style={{ width: 170 }}
          />
          <TextInput
            size="sm"
            placeholder="搜索制作商选项"
            aria-label="搜索制作商筛选选项"
            value={studioOptionQuery}
            onChange={(event) => setStudioOptionQuery(event.currentTarget.value)}
            style={{ width: 170 }}
          />
          <ActionIcon
            size="lg"
            variant={filtersOpen ? "light" : "default"}
            color={filtersOpen ? "blue" : "gray"}
            aria-label={filtersOpen ? "收起筛选" : "展开筛选"}
            onClick={() => setFiltersOpen((open) => !open)}
          >
            <IconFilter size={18} />
          </ActionIcon>
        </Group>

        <Collapse expanded={filtersOpen}>
          <Group gap="sm" align="end" wrap="wrap">
            <Select
              label="演员"
              placeholder="选择演员"
              searchable
              clearable
              nothingFoundMessage="名单中没有匹配演员"
              data={performerOptions}
              value={filters.performer || null}
              onChange={(value) => updateFilter("performer", value)}
              w={240}
            />
            <Select
              label="制作商"
              placeholder="选择制作商"
              searchable
              clearable
              nothingFoundMessage="名单中没有匹配制作商"
              data={studioOptions}
              value={filters.studio || null}
              onChange={(value) => updateFilter("studio", value)}
              w={240}
            />
          </Group>
        </Collapse>

        {activeFilters.length > 0 && (
          <Group gap="xs">
            {activeFilters.map((filter) => (
              <Badge
                key={filter.key}
                variant="light"
                rightSection={
                  <ActionIcon
                    size="xs"
                    variant="transparent"
                    color="gray"
                    aria-label={"移除" + filter.label}
                    onClick={() => removeFilter(filter.key)}
                  >
                    <IconX size={12} />
                  </ActionIcon>
                }
              >
                {filter.label}
              </Badge>
            ))}
          </Group>
        )}

        {listQuery.isError && (
          <Text size="sm" c="red">{(listQuery.error as Error).message}</Text>
        )}

        {listQuery.isLoading ? (
          <Text size="sm" c="dimmed">加载中…</Text>
        ) : (list?.items.length ?? 0) === 0 ? (
          <Text size="sm" c="dimmed" ta="center" py="xl">
            {activeFilters.length > 0 ? "没有符合筛选条件的未收录影片" : "暂无未收录影片"}
          </Text>
        ) : (
          <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
            {list?.items.map((scene) => (
              <SceneCard
                key={scene.id}
                scene={scene}
                onDelete={() => deleteMutation.mutate(scene.theporndb_uuid)}
              />
            ))}
          </SimpleGrid>
        )}

        {totalPages > 1 && (
          <Group justify="center">
            <Pagination total={totalPages} value={page} onChange={setPage} />
          </Group>
        )}
      </Stack>
    </Stack>
  );
}
