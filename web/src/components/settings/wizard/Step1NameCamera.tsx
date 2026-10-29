import { Button } from "@/components/ui/button";
import {
  Form,
  FormControl,
  FormDescription,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@/components/ui/form";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useTranslation } from "react-i18next";
import { useState, useCallback, useMemo, useRef } from "react";
import { LuEye, LuEyeOff } from "react-icons/lu";
import { Check, ChevronsUpDown } from "lucide-react";
import useSWR from "swr";
import { FrigateConfig } from "@/types/frigateConfig";
import {
  WizardFormData,
  CAMERA_BRANDS,
  CAMERA_BRAND_VALUES,
} from "@/types/cameraWizard";
import {
  cameraProfileTemplate,
  getCameraBrand,
  getCameraStreamProfile,
  type CameraBrandNote,
  type CameraProfileLabel,
} from "@/types/cameraBrands";
import {
  CAMERA_MODELS,
  cameraModelPresetBrand,
  getCameraModel,
  type CameraModel,
} from "@/types/cameraModels";
import { formatCameraStreamTemplate } from "@/utils/cameraUtil";
import { cn } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import CameraDiscovery from "./CameraDiscovery";
import CameraModelLoginGuidance from "./CameraModelLoginGuidance";

function parsePort(value?: string): number | undefined {
  if (!value || !/^\d{1,5}$/.test(value)) return undefined;
  const port = Number(value);
  return port >= 1 && port <= 65535 ? port : undefined;
}

function restorePickerFocus(event: Event, trigger: HTMLButtonElement | null) {
  // A closing popover can finish its animation after the user has already
  // moved to the next field. Don't steal focus or scroll the mobile dialog
  // back to the previous picker in that case.
  event.preventDefault();
  const active = document.activeElement;
  const content = event.currentTarget;
  if (
    !active ||
    active === document.body ||
    (content instanceof HTMLElement && content.contains(active))
  ) {
    trigger?.focus({ preventScroll: true });
  }
}

type Step1NameCameraProps = {
  wizardData: Partial<WizardFormData>;
  onUpdate: (data: Partial<WizardFormData>) => void;
  onNext: (data?: Partial<WizardFormData>) => void;
  onCancel: () => void;
  canProceed?: boolean;
};

export default function Step1NameCamera({
  wizardData,
  onUpdate,
  onNext,
  onCancel,
}: Step1NameCameraProps) {
  const { t } = useTranslation(["views/settings"]);
  const { data: config } = useSWR<FrigateConfig>("config");
  const [showPassword, setShowPassword] = useState(false);
  const [brandOpen, setBrandOpen] = useState(false);
  const [modelOpen, setModelOpen] = useState(false);
  const modelTriggerRef = useRef<HTMLButtonElement>(null);
  const brandTriggerRef = useRef<HTMLButtonElement>(null);
  const [probeMode, setProbeMode] = useState<boolean>(
    wizardData.probeMode ?? true,
  );

  const existingCameraNames = useMemo(() => {
    if (!config?.cameras) {
      return [];
    }
    return Object.keys(config.cameras);
  }, [config]);
  const sortedModels = useMemo(
    () =>
      [...CAMERA_MODELS].sort((a, b) =>
        `${a.manufacturer} ${a.name}`.localeCompare(
          `${b.manufacturer} ${b.name}`,
        ),
      ),
    [],
  );

  const step1FormData = z
    .object({
      cameraName: z
        .string()
        .min(1, t("cameraWizard.step1.errors.nameRequired"))
        .max(64, t("cameraWizard.step1.errors.nameLength"))
        .refine(
          (value) => !existingCameraNames.includes(value),
          t("cameraWizard.step1.errors.nameExists"),
        ),
      host: z.string().optional(),
      username: z.string().optional(),
      password: z.string().optional(),
      cameraModel: z.string().optional(),
      brandTemplate: z.enum(CAMERA_BRAND_VALUES).optional(),
      brandStreamProfile: z.string().optional(),
      brandChannel: z.string().optional(),
      onvifPort: z.string().optional(),
      rtspPort: z.string().optional(),
      useDigestAuth: z.boolean().optional(),
      customUrl: z.string().optional(),
    })
    .superRefine((data, ctx) => {
      const brand = getCameraBrand(data.brandTemplate);
      const custom = !probeMode && brand?.mode === "custom";
      const validPort = (value: string) => parsePort(value) !== undefined;

      if (custom) {
        const url = data.customUrl?.trim() || "";
        if (!url) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["customUrl"],
            message: t("cameraWizard.step1.errors.brandOrCustomUrlRequired"),
          });
        } else if (!url.startsWith("rtsp://") && !url.startsWith("rtsps://")) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["customUrl"],
            message: t("cameraWizard.step1.errors.customUrlRtspRequired"),
          });
        }
      } else if (!data.host?.trim()) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["host"],
          message: t("cameraWizard.step1.errors.brandOrCustomUrlRequired"),
        });
      }

      if (probeMode && !validPort(data.onvifPort || "")) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["onvifPort"],
          message: t("cameraWizard.step1.errors.invalidPort"),
        });
      }
      if (!probeMode && !custom && data.rtspPort && !validPort(data.rtspPort)) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["rtspPort"],
          message: t("cameraWizard.step1.errors.invalidPort"),
        });
      }
      if (
        !probeMode &&
        brand?.mode === "template" &&
        getCameraStreamProfile(brand, data.brandStreamProfile).path.includes(
          "{channel}",
        )
      ) {
        const channel = data.brandChannel || "";
        if (
          !/^\d{1,3}$/.test(channel) ||
          Number(channel) < 1 ||
          Number(channel) > 999
        ) {
          ctx.addIssue({
            code: z.ZodIssueCode.custom,
            path: ["brandChannel"],
            message: t("cameraWizard.step1.errors.invalidChannel"),
          });
        }
      }
    });

  const form = useForm<z.infer<typeof step1FormData>>({
    resolver: zodResolver(step1FormData),
    defaultValues: {
      cameraName: wizardData.cameraName || "",
      host: wizardData.host || "",
      username: wizardData.username || "",
      password: wizardData.password || "",
      cameraModel: getCameraModel(wizardData.cameraModel)?.id ?? "",
      brandTemplate:
        wizardData.brandTemplate &&
        CAMERA_BRAND_VALUES.includes(wizardData.brandTemplate)
          ? wizardData.brandTemplate
          : "dahua",
      brandStreamProfile: wizardData.brandStreamProfile || "main",
      brandChannel: wizardData.brandChannel || "1",
      customUrl: wizardData.customUrl || "",
      onvifPort: (wizardData.onvifPort ?? 80).toString(),
      rtspPort: wizardData.rtspPort?.toString() ?? "",
      useDigestAuth: wizardData.useDigestAuth ?? false,
    },
    mode: "onChange",
  });

  const selectedModel = getCameraModel(form.watch("cameraModel"));
  const watchedBrand = form.watch("brandTemplate");
  const watchedProfile = form.watch("brandStreamProfile");
  const watchedChannel = form.watch("brandChannel");
  const watchedName = form.watch("cameraName");
  const selectedBrand = getCameraBrand(watchedBrand);
  const selectedProfile =
    selectedBrand?.mode === "template"
      ? getCameraStreamProfile(selectedBrand, watchedProfile)
      : undefined;
  const usesCustomUrl = selectedBrand?.mode === "custom";
  const watchedHost = form.watch("host");
  const watchedCustomUrl = form.watch("customUrl");

  const hostPresent = !!(watchedHost && watchedHost.trim());
  const customPresent = !!(watchedCustomUrl && watchedCustomUrl.trim());
  const cameraNamePresent = !!watchedName?.trim();

  const isContinueButtonEnabled =
    cameraNamePresent &&
    (probeMode ? hostPresent : usesCustomUrl ? customPresent : hostPresent);

  const selectModel = (model: CameraModel) => {
    form.setValue("cameraModel", model.id, { shouldDirty: true });
    const presetValue = cameraModelPresetBrand(model);
    const brand = getCameraBrand(presetValue);
    if (brand && form.getValues("brandTemplate") !== presetValue) {
      form.setValue("brandTemplate", presetValue, { shouldDirty: true });
      form.setValue(
        "brandStreamProfile",
        brand.mode === "template"
          ? getCameraStreamProfile(brand, model.presetProfile).value
          : "",
        { shouldDirty: true },
      );
      form.clearErrors(["customUrl", "brandChannel", "rtspPort", "host"]);
    }
    // The catalog is guidance only. In particular, don't touch entered
    // credentials, a custom URL, ports, or attempt any camera connection.
    setModelOpen(false);
  };

  const onSubmit = (data: z.infer<typeof step1FormData>) => {
    onUpdate({
      ...data,
      onvifPort: parsePort(data.onvifPort) ?? 80,
      rtspPort: parsePort(data.rtspPort),
      probeMode,
    });
  };

  const handleContinue = useCallback(async () => {
    const isValid = await form.trigger();
    if (isValid) {
      const data = form.getValues();
      onNext({
        ...data,
        onvifPort: parsePort(data.onvifPort) ?? 80,
        rtspPort: parsePort(data.rtspPort),
        probeMode,
      });
    }
  }, [form, probeMode, onNext]);

  // Keep the translated labels explicit so they are discovered by i18n extraction.
  const profileLabels: Record<CameraProfileLabel, string> = {
    main: t("cameraWizard.step1.profiles.main"),
    sub: t("cameraWizard.step1.profiles.sub"),
    third: t("cameraWizard.step1.profiles.third"),
    stream1: t("cameraWizard.step1.profiles.stream1"),
    stream2: t("cameraWizard.step1.profiles.stream2"),
    profile2: t("cameraWizard.step1.profiles.profile2"),
    profile3: t("cameraWizard.step1.profiles.profile3"),
    nvrMain: t("cameraWizard.step1.profiles.nvrMain"),
    nvrSub: t("cameraWizard.step1.profiles.nvrSub"),
    vivotekLive: t("cameraWizard.step1.profiles.vivotekLive"),
    vivotekLive1s1: t("cameraWizard.step1.profiles.vivotekLive1s1"),
    mobotixMx: t("cameraWizard.step1.profiles.mobotixMx"),
    mobotixMove: t("cameraWizard.step1.profiles.mobotixMove"),
    mobotixMoveStream: t("cameraWizard.step1.profiles.mobotixMoveStream"),
  };
  const brandNotes: Record<CameraBrandNote, string> = {
    dahua: t("cameraWizard.step1.brandNotes.dahua"),
    hikvision: t("cameraWizard.step1.brandNotes.hikvision"),
    uniview: t("cameraWizard.step1.brandNotes.uniview"),
    ubiquitiLegacy: t("cameraWizard.step1.brandNotes.ubiquitiLegacy"),
    unifiProtect: t("cameraWizard.step1.brandNotes.unifiProtect"),
    reolink: t("cameraWizard.step1.brandNotes.reolink"),
    axis: t("cameraWizard.step1.brandNotes.axis"),
    tapo: t("cameraWizard.step1.brandNotes.tapo"),
    foscam: t("cameraWizard.step1.brandNotes.foscam"),
    hanwha: t("cameraWizard.step1.brandNotes.hanwha"),
    vivotek: t("cameraWizard.step1.brandNotes.vivotek"),
    sony: t("cameraWizard.step1.brandNotes.sony"),
    ipro: t("cameraWizard.step1.brandNotes.ipro"),
    avigilon: t("cameraWizard.step1.brandNotes.avigilon"),
    bosch: t("cameraWizard.step1.brandNotes.bosch"),
    milesight: t("cameraWizard.step1.brandNotes.milesight"),
    mobotix: t("cameraWizard.step1.brandNotes.mobotix"),
    grandstream: t("cameraWizard.step1.brandNotes.grandstream"),
    dlink: t("cameraWizard.step1.brandNotes.dlink"),
    ezviz: t("cameraWizard.step1.brandNotes.ezviz"),
    geovision: t("cameraWizard.step1.brandNotes.geovision"),
    acti: t("cameraWizard.step1.brandNotes.acti"),
    aiphone: t("cameraWizard.step1.brandNotes.aiphone"),
    swann: t("cameraWizard.step1.brandNotes.swann"),
    xmeye: t("cameraWizard.step1.brandNotes.xmeye"),
    eufy: t("cameraWizard.step1.brandNotes.eufy"),
    wyze: t("cameraWizard.step1.brandNotes.wyze"),
    cloud: t("cameraWizard.step1.brandNotes.cloud"),
  };
  const exampleUrl =
    selectedBrand?.mode === "template" && selectedProfile
      ? formatCameraStreamTemplate(
          cameraProfileTemplate(selectedProfile, watchedChannel),
          "192.168.1.100",
          selectedBrand.defaultPort,
          "user",
          "password",
        )
      : undefined;

  return (
    <div className="space-y-6">
      <div className="text-sm text-muted-foreground">
        {t("cameraWizard.step1.description")}
      </div>

      <Form {...form}>
        <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
          <FormField
            control={form.control}
            name="cameraName"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-primary-variant">
                  {t("cameraWizard.step1.cameraName")}
                </FormLabel>
                <FormControl>
                  <Input
                    className="h-8"
                    placeholder={t("cameraWizard.step1.cameraNamePlaceholder")}
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <CameraDiscovery
            onSelect={({ host, protocol, port }) => {
              // Discovery may select a different physical camera. Do not keep
              // model-specific login advice from the previous selection.
              form.setValue("cameraModel", "", { shouldDirty: true });
              form.setValue("host", host, {
                shouldDirty: true,
                shouldValidate: true,
              });
              if (protocol === "onvif") {
                // A new ONVIF selection must not inherit another camera's
                // hidden RTSP URL or port (or their validation errors).
                form.setValue("rtspPort", "", { shouldValidate: true });
                form.setValue("customUrl", "", { shouldValidate: true });
                form.setValue("onvifPort", String(port), {
                  shouldDirty: true,
                  shouldValidate: true,
                });
                setProbeMode(true);
                onUpdate({
                  host,
                  cameraModel: "",
                  onvifPort: port,
                  rtspPort: undefined,
                  customUrl: "",
                  probeMode: true,
                  probeResult: undefined,
                  probeCandidates: [],
                  candidateTests: {},
                  streams: [],
                });
              } else {
                // The manual RTSP flow does not use an ONVIF port; discard a
                // stale invalid value before the hidden field is validated.
                form.setValue("onvifPort", "80", { shouldValidate: true });
                form.setValue("rtspPort", String(port), {
                  shouldDirty: true,
                  shouldValidate: true,
                });
                form.setValue("brandTemplate", "other", { shouldDirty: true });
                form.setValue("customUrl", `rtsp://${host}:${port}/`, {
                  shouldDirty: true,
                  shouldValidate: true,
                });
                setProbeMode(false);
                onUpdate({
                  host,
                  cameraModel: "",
                  onvifPort: 80,
                  rtspPort: port,
                  brandTemplate: "other",
                  customUrl: `rtsp://${host}:${port}/`,
                  probeMode: false,
                  probeResult: undefined,
                  probeCandidates: [],
                  candidateTests: {},
                  streams: [],
                });
              }
            }}
          />

          <div className="space-y-4">
            <FormField
              control={form.control}
              name="host"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-primary-variant">
                    {t("cameraWizard.step1.host")}
                  </FormLabel>
                  <FormControl>
                    <Input
                      className="h-8"
                      placeholder="192.168.1.100"
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="cameraModel"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-primary-variant">
                    {t("cameraWizard.step1.cameraModel")}
                  </FormLabel>
                  <Popover open={modelOpen} onOpenChange={setModelOpen}>
                    <PopoverTrigger asChild>
                      <FormControl>
                        <Button
                          type="button"
                          variant="outline"
                          role="combobox"
                          aria-expanded={modelOpen}
                          ref={modelTriggerRef}
                          className="h-8 w-full justify-between font-normal"
                        >
                          <span className="truncate">
                            {selectedModel
                              ? `${selectedModel.manufacturer} ${selectedModel.name}`
                              : t("cameraWizard.step1.selectModel")}
                          </span>
                          <ChevronsUpDown
                            className="ml-2 size-4 shrink-0 opacity-50"
                            aria-hidden="true"
                          />
                        </Button>
                      </FormControl>
                    </PopoverTrigger>
                    <PopoverContent
                      align="start"
                      className="w-[--radix-popover-trigger-width] p-0"
                      onCloseAutoFocus={(event) =>
                        restorePickerFocus(event, modelTriggerRef.current)
                      }
                    >
                      <Command>
                        <CommandInput
                          aria-label={t("cameraWizard.step1.searchModels")}
                          placeholder={t("cameraWizard.step1.searchModels")}
                        />
                        <CommandList>
                          <CommandEmpty>
                            {t("cameraWizard.step1.noModelsFound")}
                          </CommandEmpty>
                          <CommandGroup>
                            {sortedModels.map((model) => (
                              <CommandItem
                                key={model.id}
                                value={`${model.manufacturer} ${model.name}`}
                                keywords={[
                                  model.brand,
                                  getCameraBrand(model.brand)?.label ?? "",
                                ]}
                                onSelect={() => selectModel(model)}
                              >
                                <Check
                                  aria-hidden="true"
                                  className={cn(
                                    "mr-2 size-4 shrink-0",
                                    field.value === model.id
                                      ? "opacity-100"
                                      : "opacity-0",
                                  )}
                                />
                                <span>
                                  {model.manufacturer} {model.name}
                                </span>
                              </CommandItem>
                            ))}
                          </CommandGroup>
                        </CommandList>
                      </Command>
                      <div className="border-t p-1">
                        <Button
                          type="button"
                          variant="ghost"
                          className="h-8 w-full justify-start text-xs"
                          onClick={() => {
                            field.onChange("");
                            setModelOpen(false);
                          }}
                        >
                          {t("cameraWizard.step1.modelNotListed")}
                        </Button>
                      </div>
                    </PopoverContent>
                  </Popover>
                  <FormDescription>
                    {t("cameraWizard.step1.modelDescription")}
                  </FormDescription>
                  {selectedModel && (
                    <CameraModelLoginGuidance model={selectedModel} />
                  )}
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="username"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-primary-variant">
                    {t("cameraWizard.step1.username")}
                  </FormLabel>
                  <FormControl>
                    <Input
                      className="h-8"
                      placeholder={t("cameraWizard.step1.usernamePlaceholder")}
                      {...field}
                    />
                  </FormControl>
                  <FormMessage />
                </FormItem>
              )}
            />

            <FormField
              control={form.control}
              name="password"
              render={({ field }) => (
                <FormItem>
                  <FormLabel className="text-primary-variant">
                    {t("cameraWizard.step1.password")}
                  </FormLabel>
                  <div className="relative">
                    <FormControl>
                      <Input
                        className="h-8 pr-10"
                        type={showPassword ? "text" : "password"}
                        placeholder={t(
                          "cameraWizard.step1.passwordPlaceholder",
                        )}
                        {...field}
                      />
                    </FormControl>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="absolute right-0 top-0 h-full px-3 py-2 hover:bg-transparent"
                      onClick={() => setShowPassword(!showPassword)}
                    >
                      {showPassword ? (
                        <LuEyeOff className="size-4" />
                      ) : (
                        <LuEye className="size-4" />
                      )}
                    </Button>
                  </div>
                  <FormMessage />
                </FormItem>
              )}
            />
          </div>

          <div className="space-y-3 pt-4">
            <FormLabel className="text-primary-variant">
              {t("cameraWizard.step1.detectionMethod")}
            </FormLabel>
            <RadioGroup
              value={probeMode ? "probe" : "manual"}
              onValueChange={(value) => {
                setProbeMode(value === "probe");
              }}
            >
              <div className="flex items-center space-x-2">
                <RadioGroupItem
                  value="probe"
                  id="probe-mode"
                  className={
                    probeMode
                      ? "bg-selected from-selected/50 to-selected/90 text-selected"
                      : "bg-secondary from-secondary/50 to-secondary/90 text-secondary"
                  }
                />
                <label htmlFor="probe-mode" className="cursor-pointer text-sm">
                  {t("cameraWizard.step1.probeMode")}
                </label>
              </div>
              <div className="flex items-center space-x-2">
                <RadioGroupItem
                  value="manual"
                  id="manual-mode"
                  className={
                    !probeMode
                      ? "bg-selected from-selected/50 to-selected/90 text-selected"
                      : "bg-secondary from-secondary/50 to-secondary/90 text-secondary"
                  }
                />
                <label htmlFor="manual-mode" className="cursor-pointer text-sm">
                  {t("cameraWizard.step1.manualMode")}
                </label>
              </div>
            </RadioGroup>
            <FormDescription>
              {t("cameraWizard.step1.detectionMethodDescription")}
            </FormDescription>
          </div>

          {probeMode && (
            <FormField
              control={form.control}
              name="onvifPort"
              render={({ field, fieldState }) => (
                <FormItem>
                  <FormLabel className="text-primary-variant">
                    {t("cameraWizard.step1.onvifPort")}
                  </FormLabel>
                  <FormControl>
                    <Input
                      className="h-8"
                      type="text"
                      {...field}
                      placeholder="80"
                    />
                  </FormControl>
                  <FormDescription>
                    {t("cameraWizard.step1.onvifPortDescription")}
                  </FormDescription>
                  <FormMessage>
                    {fieldState.error ? fieldState.error.message : null}
                  </FormMessage>
                </FormItem>
              )}
            />
          )}

          {probeMode && (
            <FormField
              control={form.control}
              name="useDigestAuth"
              render={({ field }) => (
                <FormItem className="flex items-start space-x-2">
                  <FormControl>
                    <Checkbox
                      className="size-5 text-white accent-white data-[state=checked]:bg-selected data-[state=checked]:text-white"
                      checked={!!field.value}
                      onCheckedChange={(val) => field.onChange(!!val)}
                    />
                  </FormControl>
                  <div className="flex flex-1 flex-col space-y-1">
                    <FormLabel className="mb-0 text-primary-variant">
                      {t("cameraWizard.step1.useDigestAuth")}
                    </FormLabel>
                    <FormDescription className="mt-0">
                      {t("cameraWizard.step1.useDigestAuthDescription")}
                    </FormDescription>
                  </div>
                </FormItem>
              )}
            />
          )}

          {!probeMode && (
            <div className="space-y-4">
              <FormField
                control={form.control}
                name="brandTemplate"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-primary-variant">
                      {t("cameraWizard.step1.cameraBrand")}
                    </FormLabel>
                    <Popover open={brandOpen} onOpenChange={setBrandOpen}>
                      <PopoverTrigger asChild>
                        <FormControl>
                          <Button
                            type="button"
                            variant="outline"
                            role="combobox"
                            aria-expanded={brandOpen}
                            ref={brandTriggerRef}
                            className="h-8 w-full justify-between font-normal"
                          >
                            <span className="truncate">
                              {selectedBrand?.value === "other"
                                ? t("label.other", { ns: "common" })
                                : selectedBrand?.label ||
                                  t("cameraWizard.step1.selectBrand")}
                            </span>
                            <ChevronsUpDown
                              className="ml-2 size-4 shrink-0 opacity-50"
                              aria-hidden="true"
                            />
                          </Button>
                        </FormControl>
                      </PopoverTrigger>
                      <PopoverContent
                        align="start"
                        className="w-[--radix-popover-trigger-width] p-0"
                        onCloseAutoFocus={(event) =>
                          restorePickerFocus(event, brandTriggerRef.current)
                        }
                      >
                        <Command>
                          <CommandInput
                            aria-label={t("cameraWizard.step1.searchBrands")}
                            placeholder={t("cameraWizard.step1.searchBrands")}
                          />
                          <CommandList>
                            <CommandEmpty>
                              {t("cameraWizard.step1.noBrandsFound")}
                            </CommandEmpty>
                            <CommandGroup>
                              {CAMERA_BRANDS.map((brand) => {
                                const label =
                                  brand.value === "other"
                                    ? t("label.other", { ns: "common" })
                                    : brand.label;
                                return (
                                  <CommandItem
                                    key={brand.value}
                                    value={label}
                                    keywords={[brand.value, brand.label]}
                                    onSelect={() => {
                                      field.onChange(brand.value);
                                      // Other is a fallback, not a conflicting
                                      // manufacturer; keep the model advice.
                                      if (
                                        selectedModel &&
                                        brand.value !== "other" &&
                                        brand.value !== selectedModel.brand
                                      ) {
                                        form.setValue("cameraModel", "", {
                                          shouldDirty: true,
                                        });
                                      }
                                      form.setValue(
                                        "brandStreamProfile",
                                        brand.mode === "template"
                                          ? brand.profiles[0].value
                                          : "",
                                        { shouldDirty: true },
                                      );
                                      form.clearErrors([
                                        "customUrl",
                                        "brandChannel",
                                        "rtspPort",
                                        "host",
                                      ]);
                                      setBrandOpen(false);
                                    }}
                                  >
                                    <Check
                                      aria-hidden="true"
                                      className={cn(
                                        "mr-2 size-4 shrink-0",
                                        field.value === brand.value
                                          ? "opacity-100"
                                          : "opacity-0",
                                      )}
                                    />
                                    {label}
                                  </CommandItem>
                                );
                              })}
                            </CommandGroup>
                          </CommandList>
                        </Command>
                      </PopoverContent>
                    </Popover>
                    <FormDescription>
                      {t("cameraWizard.step1.brandCompatibility")}
                      {selectedBrand?.note && (
                        <span className="mt-1 block">
                          {brandNotes[selectedBrand.note]}
                        </span>
                      )}
                    </FormDescription>
                    <FormMessage />
                  </FormItem>
                )}
              />

              {selectedBrand?.mode === "template" &&
                selectedBrand.profiles.length > 1 && (
                  <FormField
                    control={form.control}
                    name="brandStreamProfile"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-primary-variant">
                          {t("cameraWizard.step1.streamProfile")}
                        </FormLabel>
                        <Select
                          onValueChange={field.onChange}
                          value={selectedProfile?.value}
                        >
                          <FormControl>
                            <SelectTrigger className="h-8">
                              <SelectValue />
                            </SelectTrigger>
                          </FormControl>
                          <SelectContent>
                            {selectedBrand.profiles.map((profile) => (
                              <SelectItem
                                key={profile.value}
                                value={profile.value}
                              >
                                {profileLabels[profile.label]}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                        <FormDescription>
                          {t("cameraWizard.step1.streamProfileDescription")}
                        </FormDescription>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                )}

              {selectedProfile?.path.includes("{channel}") && (
                <FormField
                  control={form.control}
                  name="brandChannel"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-primary-variant">
                        {t("cameraWizard.step1.channel")}
                      </FormLabel>
                      <FormControl>
                        <Input className="h-8" inputMode="numeric" {...field} />
                      </FormControl>
                      <FormDescription>
                        {t("cameraWizard.step1.channelDescription")}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              {exampleUrl && (
                <p className="break-all text-sm text-muted-foreground">
                  {t("cameraWizard.step1.brandUrlFormat", { exampleUrl })}
                </p>
              )}

              {!usesCustomUrl && selectedBrand && (
                <FormField
                  control={form.control}
                  name="rtspPort"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-primary-variant">
                        {t("cameraWizard.step1.rtspPort")}
                      </FormLabel>
                      <FormControl>
                        <Input
                          className="h-8"
                          inputMode="numeric"
                          placeholder={t(
                            "cameraWizard.step1.rtspPortPlaceholder",
                          )}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        {t("cameraWizard.step1.rtspPortWithDefault", {
                          port: selectedBrand.defaultPort,
                        })}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}

              {usesCustomUrl && (
                <FormField
                  control={form.control}
                  name="customUrl"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel className="text-primary-variant">
                        {t("cameraWizard.step1.customUrl")}
                      </FormLabel>
                      <FormControl>
                        <Input
                          className="h-8"
                          placeholder={t(
                            "cameraWizard.step1.customUrlPlaceholder",
                          )}
                          {...field}
                        />
                      </FormControl>
                      <FormDescription>
                        {selectedBrand?.mode === "custom" &&
                        selectedBrand.credentials === "asProvided" ? (
                          <>
                            {t("cameraWizard.step1.copyUrlDescription")}{" "}
                            {t("cameraWizard.step1.copyUrlCredentialsHelp")}
                          </>
                        ) : (
                          <>
                            {t("cameraWizard.step1.customUrlDescription")}{" "}
                            {t("cameraWizard.step1.customUrlCredentialsHelp")}
                          </>
                        )}
                      </FormDescription>
                      <FormMessage />
                    </FormItem>
                  )}
                />
              )}
            </div>
          )}
        </form>
      </Form>

      <div className="flex flex-col-reverse gap-2 pt-3 sm:flex-row sm:justify-end">
        <Button type="button" onClick={onCancel} className="sm:flex-1">
          {t("button.cancel", { ns: "common" })}
        </Button>
        <Button
          type="button"
          onClick={handleContinue}
          disabled={!isContinueButtonEnabled}
          variant="select"
          className="flex items-center justify-center gap-2 sm:flex-1"
        >
          {t("button.continue", { ns: "common" })}
        </Button>
      </div>
    </div>
  );
}
