import type * as Preset from "@docusaurus/preset-classic";
import * as path from "node:path";
import type { Config, PluginConfig } from "@docusaurus/types";
import type * as OpenApiPlugin from "docusaurus-plugin-openapi-docs";

// Bump when a new stable release ships
const STABLE_VERSION = "0.18";

const config: Config = {
  title: "Gannet",
  tagline: "NVR with realtime object detection for IP cameras, native on Windows",
  // FIXME(owner): must be the origin this documentation is actually served from.
  // While it points at Frigate's host, the generated canonical URLs and sitemap
  // advertise upstream's site instead of ours.
  url: "https://docs.frigate.video",
  baseUrl: "/",
  onBrokenLinks: "throw",
  onBrokenMarkdownLinks: "warn",
  favicon: "img/branding/favicon.ico",
  // Machine-readable rights reservations, published alongside the site so that
  // automated readers can find them without reading the license. TDMRep is the
  // W3C community format recognized for Article 4(3) reservations under the EU
  // Copyright Directive; `noai`/`noimageai` are read by some crawlers and search
  // engines. These are reservations of statutory exceptions, not licenses: they
  // do not and cannot restrict the MIT-licensed upstream content, and they do not
  // change what humans may do with the code. See LICENSING.md in the repository.
  headTags: [
    {
      tagName: "meta",
      attributes: { name: "tdm-reservation", content: "1" },
    },
    {
      tagName: "meta",
      attributes: {
        name: "tdm-policy",
        content:
          "https://github.com/unsubstantiation/gannet/blob/dev/LICENSING.md",
      },
    },
    {
      tagName: "meta",
      attributes: { name: "robots", content: "noai, noimageai" },
    },
  ],
  organizationName: "unsubstantiation",
  projectName: "gannet",
  themes: [
    "@docusaurus/theme-mermaid",
    "docusaurus-theme-openapi-docs",
    "@inkeep/docusaurus/chatButton",
    "@inkeep/docusaurus/searchBar",
  ],
  markdown: {
    mermaid: true,
  },
  i18n: {
    defaultLocale: "en",
    locales: ["en"],
    localeConfigs: {
      en: {
        label: "English",
      },
    },
  },
  themeConfig: {
    announcementBar: {
      id: "gannet_fork",
      content: `
        Gannet is an independent, non-commercial fork of Frigate, built to run natively on Windows.
        <a style="margin-left: 8px; color: inherit; text-decoration: underline;" target="_blank" rel="noopener noreferrer" href="https://github.com/unsubstantiation/gannet/blob/dev/LICENSING.md">What that means for you</a>`,
      backgroundColor: "#005f73",
      textColor: "#e0fbfc",
      isCloseable: false,
    },
    docs: {
      sidebar: {
        hideable: true,
      },
    },
    inkeepConfig: {
      baseSettings: {
        apiKey: "b1a4c4d73c9b48aa5b3cdae6e4c81f0bb3d1134eeb5a7100",
        integrationId: "cm6xmhn9h000gs601495fkkdx",
        organizationId: "org_map2JQEOco8U1ZYY",
        primaryBrandColor: "#010101",
      },
      aiChatSettings: {
        chatSubjectName: "Gannet",
        botAvatarSrcUrl:
          "https://raw.githubusercontent.com/unsubstantiation/gannet/dev/docs/static/img/branding/gannet.png",
        getHelpCallToActions: [
          {
            name: "GitHub",
            url: "https://github.com/unsubstantiation/gannet",
            icon: {
              builtIn: "FaGithub",
            },
          },
        ],
        quickQuestions: [
          "How to configure and setup camera settings?",
          "How to setup notifications?",
          "Supported builtin detectors?",
          "How to restream video feed?",
          "How can I get sound or audio in my recordings?",
        ],
      },
    },
    prism: {
      magicComments: [
        {
          className: "theme-code-block-highlighted-line",
          line: "highlight-next-line",
          block: { start: "highlight-start", end: "highlight-end" },
        },
        {
          className: "code-block-error-line",
          line: "highlight-error-line",
        },
      ],
      additionalLanguages: ["bash", "json"],
    },
    languageTabs: [
      {
        highlight: "python",
        language: "python",
        logoClass: "python",
      },
      {
        highlight: "javascript",
        language: "nodejs",
        logoClass: "nodejs",
      },
      {
        highlight: "javascript",
        language: "javascript",
        logoClass: "javascript",
      },
      {
        highlight: "bash",
        language: "curl",
        logoClass: "curl",
      },
      {
        highlight: "rust",
        language: "rust",
        logoClass: "rust",
      },
    ],
    navbar: {
      title: "Gannet",
      logo: {
        alt: "Gannet",
        src: "img/branding/gannet.png",
      },
      items: [
        {
          href: "https://github.com/unsubstantiation/gannet/releases",
          label: `${STABLE_VERSION}`,
          position: "left",
        },
        {
          to: "/",
          activeBasePath: "docs",
          label: "Docs",
          position: "left",
        },
        {
          href: "https://fairuniversal.com",
          label: "Website",
          position: "right",
        },
        {
          type: "localeDropdown",
          position: "right",
          dropdownItemsAfter: [
            {
              label: "简体中文（社区翻译）",
              href: "https://docs.frigate-cn.video",
            },
          ],
        },
        {
          href: "https://github.com/unsubstantiation/gannet",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Community",
          items: [
            {
              label: "GitHub",
              href: "https://github.com/unsubstantiation/gannet",
            },
            {
              label: "Discussions",
              href: "https://github.com/unsubstantiation/gannet/discussions",
            },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} unsubstantiation. Documentation derived from Frigate, © the Frigate authors (MIT).`,
    },
  },
  plugins: [
    path.resolve(__dirname, "plugins", "raw-loader"),
    path.resolve(__dirname, "plugins", "yaml-loader"),
    [
      "docusaurus-plugin-openapi-docs",
      {
        id: "openapi",
        docsPluginId: "classic", // configured for preset-classic
        config: {
          frigateApi: {
            specPath: "static/frigate-api.yaml",
            outputDir: "docs/integrations/api",
            sidebarOptions: {
              groupPathsBy: "tag",
              categoryLinkSource: "tag",
              sidebarCollapsible: true,
              sidebarCollapsed: true,
            },
            showSchemas: true,
          } satisfies OpenApiPlugin.Options,
        },
      },
    ],
  ] as PluginConfig[],
  presets: [
    [
      "classic",
      {
        docs: {
          routeBasePath: "/",
          sidebarPath: "./sidebars.ts",
          editUrl:
            "https://github.com/unsubstantiation/gannet/edit/dev/docs/",
          sidebarCollapsible: false,
          docItemComponent: "@theme/ApiItem", // Derived from docusaurus-theme-openapi
        },

        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],
};

export default async function createConfig() {
  return config;
}
