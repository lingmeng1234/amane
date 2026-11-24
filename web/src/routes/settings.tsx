import {
  Alert,
  Box,
  Button,
  Collapse,
  Center,
  Group,
  Loader,
  NavLink,
  Modal,
  Paper,
  Popover,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  Title,
  UnstyledButton,
} from "@mantine/core";
import { IconAlertCircle, IconChevronDown, IconInfoCircle, IconPlugConnected, IconRefresh } from "@tabler/icons-react";
import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { z } from "zod";
import { isHidden, resolveSchema, type JSONSchemaObject } from "@/components/schema-form/schema";
import { SchemaForm } from "@/components/schema-form/schema-form";
import { useConfig, useConfigSchema, useUpdateConfig } from "@/hooks/use-config";
import { useNarrowViewport } from "@/hooks/use-narrow-viewport";
import { extractErrorMessage } from "@/lib/api-error";
import { apiFetch } from "@/lib/api-token";
import { notifications } from "@mantine/notifications";

const settingsSearchSchema = z.object({
  section: z.string().optional(),
});

const DEFAULT_UNCENSORED_STREAMING_NUMBER_RULES = [
  "[0-9]{6}[-_][0-9]{2,3}",
  "N[0-9]+",
  "HEYZO-[0-9]{4}",
];

// Keep these values aligned with ScrapingConfig defaults in src/amane/config/manager.py.
const DEFAULT_CONTENT_ROUTES = {
  censored: ["dmm", "mgstage", "avsox", "avbase", "javbus"],
  uncensored_dvd: ["aventertainments", "caribbeancom_index", "avsox"],
  uncensored_streaming: [
    "10musume",
    "1pondo",
    "caribbeancom",
    "pacopacomama",
    "heyzo",
    "tokyo_hot",
    "caribbeancompr",
    "d2pass",
    "avsox",
  ],
  chinese: [],
  western: ["theporndb"],
  fc2: ["fc2"],
  amateur: ["mgstage", "dmm"],
  hentai: ["dmm", "hanime1"],
};

const NFO_CATEGORIES = [
  ["basic_info", "基础信息"],
  ["plot_release", "剧情与发行信息"],
  ["people", "人员与制作信息"],
  ["categories", "分类与系列"],
  ["images", "图片与视频"],
  ["ratings", "评分"],
] as const;

function RestoreDefaultButton({
  field,
  defaultValue,
  setValue,
}: {
  field: string;
  defaultValue: unknown;
  setValue: (value: unknown) => void;
}) {
  const { t } = useTranslation("settings");

  return (
    <Button
      key={field}
      size="xs"
      variant="subtle"
      leftSection={<IconRefresh size={14} />}
      onClick={() => setValue(defaultValue)}
    >
      {t("restoreDefault")}
    </Button>
  );
}

const POSTER_FACE_SOURCES = [
  { id: "10musume", label: "10musume" },
  { id: "1pondo", label: "1pondo" },
  { id: "caribbeancom", label: "Caribbeancom" },
  { id: "pacopacomama", label: "Pacopacomama" },
  { id: "caribbeancompr", label: "Caribbeancompr" },
  { id: "caribbeancom_index", label: "Caribbeancom Index" },
  { id: "d2pass", label: "D2Pass" },
  { id: "heyzo", label: "Heyzo" },
] as const;

function FaceDetectionHelp() {
  const { t } = useTranslation("settings");
  return (
    <Popover width={340} position="bottom" withArrow shadow="md">
      <Popover.Target>
        <Button
          type="button"
          size="xs"
          variant="subtle"
          color="blue"
          leftSection={<IconInfoCircle size={14} />}
        >
          {t("faceDetection.helpLink")}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Text size="sm">{t("faceDetection.helpBody")}</Text>
      </Popover.Dropdown>
    </Popover>
  );
}

function FaceDetectionSourceSettings({
  savedSources,
  saving,
  onSave,
}: {
  savedSources: string[];
  saving: boolean;
  onSave: (sources: string[]) => void;
}) {
  const { t } = useTranslation("settings");
  const [expanded, setExpanded] = useState(false);
  const [draft, setDraft] = useState<string[]>(savedSources);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const changed =
    draft.length !== savedSources.length ||
    draft.some((source) => !savedSources.includes(source));

  return (
    <>
      <Paper withBorder p="sm">
        <UnstyledButton
          onClick={() => setExpanded((current) => !current)}
          style={{ width: "100%", textAlign: "left" }}
        >
          <Group justify="space-between" wrap="nowrap">
            <Box style={{ minWidth: 0 }}>
              <Text size="sm" fw={600}>
                {t("faceDetection.sourceSelection")}
              </Text>
              <Text size="xs" c="dimmed">
                {t("faceDetection.sourceDescription")}
              </Text>
            </Box>
            <Group gap="xs" wrap="nowrap">
              <Text size="xs" c="dimmed" style={{ whiteSpace: "nowrap" }}>
                {t("faceDetection.selectedCount", { count: draft.length })}
              </Text>
              <IconChevronDown
                size={16}
                style={{
                  flexShrink: 0,
                  transform: expanded ? "rotate(180deg)" : undefined,
                  transition: "transform 150ms ease",
                }}
              />
            </Group>
          </Group>
        </UnstyledButton>
        <Collapse expanded={expanded}>
          <Stack gap="sm" mt="md">
            <SimpleGrid cols={{ base: 1, sm: 2 }} spacing="sm">
              {POSTER_FACE_SOURCES.map((source) => (
                <Switch
                  key={source.id}
                  label={source.label}
                  checked={draft.includes(source.id)}
                  onChange={(event) => {
                    const checked = event.currentTarget.checked;
                    setDraft((current) =>
                      checked
                        ? [...current, source.id]
                        : current.filter((value) => value !== source.id),
                    );
                  }}
                />
              ))}
            </SimpleGrid>
            <Group justify="flex-end">
              <Button
                size="xs"
                variant="default"
                disabled={!changed || saving}
                onClick={() => setDraft(savedSources)}
              >
                {t("faceDetection.discard")}
              </Button>
              <Button
                type="button"
                size="xs"
                disabled={!changed || saving}
                loading={saving}
                onClick={() => setConfirmOpen(true)}
              >
                {t("faceDetection.save")}
              </Button>
            </Group>
          </Stack>
        </Collapse>
      </Paper>

      <Modal
        opened={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title={t("faceDetection.confirmTitle")}
        centered
      >
        <Stack gap="md">
          <Text size="sm">
            {t("faceDetection.confirmBody", { count: draft.length })}
          </Text>
          <Group justify="flex-end">
            <Button type="button" variant="default" onClick={() => setConfirmOpen(false)}>
              {t("faceDetection.cancel")}
            </Button>
            <Button
              type="button"
              loading={saving}
              onClick={() => {
                onSave(draft);
                setConfirmOpen(false);
              }}
            >
              {t("faceDetection.confirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </>
  );
}

function scrapingFieldActions(field: string, setValue: (value: unknown) => void) {
  if (field === "poster_crop_detect_face") return <FaceDetectionHelp />;

  const defaults: Record<string, unknown> = {
    poster_ratio: 0.7,
    uncensored_poster_ratio: 0.87,
    poster_crop_skip_ratio: 0.9,
    content_routes: DEFAULT_CONTENT_ROUTES,
    uncensored_streaming_number_rules: DEFAULT_UNCENSORED_STREAMING_NUMBER_RULES,
    number_mapping_rules: [],
    mosaic_rules: { cracked: "破解,克破,CRACKED,-U,-UC", leaked: "流出,LEAKED" },
  };

  if (!(field in defaults)) return null;

  return <RestoreDefaultButton field={field} defaultValue={defaults[field]} setValue={setValue} />;
}

interface NfoOutputSettingsProps {
  schema: JSONSchemaObject;
  values: Record<string, unknown>;
  saving: boolean;
  onSave: (categoryKey: string, fullCategory: Record<string, unknown>) => void;
}

function NfoOutputSettings({ schema, values, saving, onSave }: NfoOutputSettingsProps) {
  const { t } = useTranslation("settings");

  const [activeCategory, setActiveCategory] = useState<string>("basic_info");

  const categories = NFO_CATEGORIES.filter(([key]) => {
    const categorySchema = schema.properties?.[key];
    return categorySchema !== undefined && typeof categorySchema !== "boolean";
  });

  const activeDefinition = categories.find(([key]) => key === activeCategory);
  const activeKey = activeDefinition?.[0] ?? categories[0]?.[0];

  if (!activeKey) return null;

  const categorySchema = schema.properties?.[activeKey];
  if (!categorySchema || typeof categorySchema === "boolean") return null;

  const categoryValues = (values[activeKey] as Record<string, unknown> | undefined) ?? {};

  const categoryTitle = String(
    t(`fields.nfo_output.${activeKey}.label` as never, {
      defaultValue: activeDefinition?.[1] ?? activeKey,
    }),
  );

  return (
    <Stack gap="md">
      <Tabs
        value={activeKey}
        onChange={(value) => {
          if (value) setActiveCategory(value);
        }}
        variant="pills"
        keepMounted={false}
      >
        <Tabs.List style={{ flexWrap: "wrap" }}>
          {categories.map(([key, fallbackLabel]) => {
            const label = String(
              t(`fields.nfo_output.${key}.label` as never, {
                defaultValue: fallbackLabel,
              }),
            );

            return (
              <Tabs.Tab key={key} value={key}>
                {label}
              </Tabs.Tab>
            );
          })}
        </Tabs.List>
      </Tabs>

      <Text fw={600}>{categoryTitle}</Text>

      {activeKey === "categories" ? (
        <SimpleGrid cols={{ base: 1, md: 3 }} spacing="md">
          {(["genre", "tag", "series"] as const).map((columnKey) => {
            const propertySchema = categorySchema.properties?.[columnKey];
            if (!propertySchema) return null;
            const isSeries = columnKey === "series";
            const columnSchema: JSONSchemaObject = isSeries
              ? { type: "object", properties: { series: propertySchema } }
              : propertySchema;
            const columnValues = isSeries
              ? { series: categoryValues.series }
              : ((categoryValues[columnKey] as Record<string, unknown> | undefined) ?? {});
            const columnTitle = String(
              t(`fields.nfo_output.categories.${columnKey}.label` as never, {
                defaultValue: columnKey,
              }),
            );

            return (
              <Paper key={columnKey} withBorder p="sm">
                <Text fw={600} mb="sm">
                  {columnTitle}
                </Text>
                <SchemaForm
                  key={`${columnKey}:${JSON.stringify(columnValues)}`}
                  schema={columnSchema}
                  prefix={isSeries ? "categories" : columnKey}
                  values={columnValues}
                  i18nPrefix="settings:fields.nfo_output"
                  actionsPlacement="affix"
                  fieldLayout="checkbox-grid"
                  onSave={(patch) => {
                    const fullCategory = isSeries
                      ? { ...categoryValues, ...patch }
                      : { ...categoryValues, [columnKey]: { ...columnValues, ...patch } };
                    onSave(activeKey, fullCategory);
                  }}
                  saving={saving}
                />
              </Paper>
            );
          })}
        </SimpleGrid>
      ) : (
        <SchemaForm
          key={`${activeKey}:${JSON.stringify(categoryValues)}`}
          schema={categorySchema}
          prefix={activeKey}
          values={categoryValues}
          i18nPrefix="settings:fields.nfo_output"
          actionsPlacement="affix"
          fieldLayout="checkbox-grid"
          onSave={(patch) => {
            const fullCategory = {
              ...categoryValues,
              ...patch,
            };
            onSave(activeKey, fullCategory);
          }}
          saving={saving}
        />
      )}
    </Stack>
  );
}

export const Route = createFileRoute("/settings")({
  validateSearch: settingsSearchSchema,
  component: SettingsPage,
});

function SettingsPage() {
  const { t } = useTranslation("settings");
  const { section } = Route.useSearch();
  const navigate = Route.useNavigate();
  const narrow = useNarrowViewport("md");
  const { data: schema, isLoading: schemaLoading, error: schemaError } = useConfigSchema();
  const { data: values, isLoading: valuesLoading, error: valuesError } = useConfig();
  const saveMutation = useUpdateConfig();
  const [testingMediaServer, setTestingMediaServer] = useState(false);

  async function testMediaServer() {
    const mediaServer = (values as Record<string, unknown> | undefined)?.media_server;
    if (!mediaServer) return;
    setTestingMediaServer(true);
    try {
      const response = await apiFetch("/api/config/media-server/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(mediaServer),
      });
      const result = (await response.json().catch(() => ({}))) as {
        detail?: string;
        people_count?: number;
      };
      if (!response.ok) throw new Error(result.detail ?? `HTTP ${response.status}`);
      notifications.show({
        message: t("mediaServer.testSuccess", { count: result.people_count ?? 0 }),
        color: "green",
      });
    } catch (err) {
      notifications.show({
        message: extractErrorMessage(err, t("mediaServer.testFailed")),
        color: "red",
      });
    } finally {
      setTestingMediaServer(false);
    }
  }

  const resolvedSchema = useMemo(() => (schema ? resolveSchema(schema, schema) : null), [schema]);

  const sectionKeys = useMemo(() => {
    if (!resolvedSchema?.properties) return [];
    return Object.entries(resolvedSchema.properties)
      .filter(([, value]) => typeof value !== "boolean" && !isHidden(value))
      .map(([key]) => key);
  }, [resolvedSchema]);

  const currentSection =
    (section && sectionKeys.includes(section) ? section : sectionKeys[0]) ?? null;

  const loading = schemaLoading || valuesLoading;
  const error = schemaError ?? valuesError;

  return (
    <Stack gap="md" pb={160}>
      <Title order={2}>{t("title")}</Title>

      {loading && (
        <Center py="xl">
          <Loader size="sm" />
        </Center>
      )}

      {error && (
        <Alert icon={<IconAlertCircle size={18} />} color="red" variant="light">
          {extractErrorMessage(error, t("config.loadError"))}
        </Alert>
      )}

      {!loading && !error && resolvedSchema && values && currentSection && (
        <Group align="flex-start" gap="lg" wrap={narrow ? "wrap" : "nowrap"}>
          {narrow ? (
            // 窄屏侧栏与表单无法并排: 220px 固定导航会把字段压到几十像素宽.
            <Select
              w="100%"
              allowDeselect={false}
              value={currentSection}
              onChange={(key) => {
                if (key) void navigate({ search: { section: key } });
              }}
              data={sectionKeys.map((key) => ({
                value: key,
                // Schema 顶层分组名运行时才知, 动态表单例外.
                label: t(`tabs.${key}` as never, { defaultValue: key }),
              }))}
            />
          ) : (
            <Paper withBorder p="xs" w={220} style={{ position: "sticky", top: 12, flexShrink: 0 }}>
              <Stack gap={4}>
                {sectionKeys.map((key) => (
                  <NavLink
                    key={key}
                    // Schema 顶层分组名运行时才知, 动态表单例外.
                    label={t(`tabs.${key}` as never, { defaultValue: key })}
                    active={currentSection === key}
                    onClick={() => void navigate({ search: { section: key } })}
                    variant="filled"
                    style={{ borderRadius: "var(--mantine-radius-md)" }}
                  />
                ))}
              </Stack>
            </Paper>
          )}

          <Box style={{ flex: 1, minWidth: 0 }}>
            {sectionKeys.map((key) => {
              if (key !== currentSection) return null;
              const sectionSchema = resolvedSchema.properties?.[key];
              if (!sectionSchema || typeof sectionSchema === "boolean") return null;
              // Schema 顶层 key 运行时才知; 桥接到按 section 切分的表单 values.
              const sectionValues = (values as Record<string, Record<string, unknown>>)[key] ?? {};
              const savedFaceSources = Array.isArray(sectionValues.poster_crop_face_sources)
                ? (sectionValues.poster_crop_face_sources as string[])
                : POSTER_FACE_SOURCES.map((source) => source.id);

              return (
                <Paper key={key} withBorder p="md">
                  <Text fw={600} mb="md">
                    {/* Schema 顶层分组名运行时才知, 动态表单例外. */}
                    {t(`tabs.${key}` as never, { defaultValue: key })}
                  </Text>

                  {key === "nfo_output" ? (
                    <NfoOutputSettings
                      schema={sectionSchema}
                      values={sectionValues}
                      saving={saveMutation.isPending}
                      onSave={(categoryKey, fullCategory) =>
                        saveMutation.mutate({
                          body: {
                            nfo_output: {
                              [categoryKey]: fullCategory,
                            },
                          },
                        })
                      }
                    />
                  ) : (
                    <>
                      {key === "media_server" ? (
                        <Group justify="flex-end" mb="md">
                          <Button
                            size="sm"
                            variant="light"
                            leftSection={<IconPlugConnected size={16} />}
                            loading={testingMediaServer}
                            onClick={() => void testMediaServer()}
                          >
                            {t("mediaServer.testConnection")}
                          </Button>
                        </Group>
                      ) : null}

                      <SchemaForm
                        schema={
                          key === "scraping"
                            ? {
                                ...sectionSchema,
                                properties: Object.fromEntries(
                                  Object.entries(sectionSchema.properties ?? {}).filter(
                                    ([field]) => field !== "poster_crop_face_sources",
                                  ),
                                ),
                              }
                            : sectionSchema
                        }
                        prefix={key}
                        values={
                          key === "scraping"
                            ? Object.fromEntries(
                                Object.entries(sectionValues).filter(
                                  ([field]) => field !== "poster_crop_face_sources",
                                ),
                              )
                            : sectionValues
                        }
                        i18nPrefix="settings:fields"
                        actionsPlacement="affix"
                        fieldActions={key === "scraping" ? scrapingFieldActions : undefined}
                        afterFieldKey={
                          key === "scraping"
                            ? "poster_crop_detect_face"
                            : undefined
                        }
                        afterField={
                          key === "scraping" ? (
                            <FaceDetectionSourceSettings
                              key={savedFaceSources.join("|")}
                              savedSources={savedFaceSources}
                              saving={saveMutation.isPending}
                              onSave={(sources) =>
                                saveMutation.mutate({
                                  body: { scraping: { poster_crop_face_sources: sources } },
                                })
                              }
                            />
                          ) : undefined
                        }
                        onSave={(patch) => saveMutation.mutate({ body: { [key]: patch } })}
                        saving={saveMutation.isPending}
                      />
                    </>
                  )}
                </Paper>
              );
            })}
          </Box>
        </Group>
      )}
    </Stack>
  );
}
