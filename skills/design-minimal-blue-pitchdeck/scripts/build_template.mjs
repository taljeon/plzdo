import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { Presentation, PresentationFile } from "@oai/artifact-tool";

const SIZE = { width: 960, height: 540 };
const C = {
  canvas: "#F1F5F9",
  cobalt: "#364EF0",
  indigo: "#3A3CB6",
  violetMid: "#7A80D6",
  violetLight: "#B9C3F6",
  cobaltSoft: "#93A1F4",
  ink: "#333333",
  graphite: "#606264",
  gray: "#797B7D",
  rule: "#A8ABAE",
  timeline: "#DDE3EA",
  paper: "#FFFFFF",
  black: "#000000",
};

const FONT_LATIN = "Avenir Next";
const FONT_KOREAN = "Apple SD Gothic Neo";

function parseArgs(argv) {
  const args = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (!token.startsWith("--")) continue;
    const key = token.slice(2);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      args[key] = true;
    } else {
      args[key] = value;
      index += 1;
    }
  }
  return args;
}

function usesKorean(text) {
  return /[\u3131-\uD79D]/u.test(text);
}

function addText(slide, text, position, options = {}) {
  const shape = slide.shapes.add({
    geometry: "textbox",
    name: options.name,
    position,
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  shape.text = text;
  shape.text.style = {
    fontSize: options.fontSize ?? 14,
    typeface:
      options.typeface ?? (usesKorean(text) ? FONT_KOREAN : FONT_LATIN),
    color: options.color ?? C.ink,
    bold: options.bold ?? false,
    alignment: options.alignment ?? "left",
    verticalAlignment: options.verticalAlignment ?? "top",
    lineSpacing: options.lineSpacing ?? 1.12,
    wrap: options.wrap ?? "square",
    autoFit: options.autoFit ?? "shrinkText",
    insets: options.insets ?? { top: 0, right: 0, bottom: 0, left: 0 },
  };
  return shape;
}

function addRect(slide, position, options = {}) {
  return slide.shapes.add({
    geometry: options.geometry ?? "rect",
    name: options.name,
    position,
    fill: options.fill ?? "none",
    line:
      options.line ??
      ({ style: "solid", fill: options.lineColor ?? "none", width: 0 }),
    borderRadius: options.borderRadius,
  });
}

function addLine(slide, left, top, width, height, options = {}) {
  return slide.shapes.add({
    geometry: "line",
    name: options.name,
    position: { left, top, width, height },
    fill: "none",
    line: {
      style: options.style ?? "solid",
      fill: options.color ?? C.black,
      width: options.weight ?? 1,
    },
  });
}

function addBaseSlide(presentation, name) {
  const slide = presentation.slides.add();
  slide.background.fill = C.canvas;
  addRect(
    slide,
    { left: 0, top: 0, width: SIZE.width, height: SIZE.height },
    {
      name: `${name}-canvas-frame`,
      fill: "none",
      line: { style: "solid", fill: C.gray, width: 1 },
    },
  );
  return slide;
}

function addSingleTitle(slide, text, options = {}) {
  return addText(
    slide,
    text,
    {
      left: options.left ?? 50,
      top: options.top ?? 50,
      width: options.width ?? 400,
      height: options.height ?? 43,
    },
    {
      name: options.name ?? "slide-title",
      fontSize: options.fontSize ?? 31,
      color: C.cobalt,
      bold: options.bold ?? true,
      wrap: "none",
      autoFit: "shrinkText",
    },
  );
}

function addSplitTitle(slide, parts) {
  for (const part of parts) {
    addText(
      slide,
      part.text,
      { left: part.left, top: 50, width: part.width, height: 43 },
      {
        name: part.name,
        fontSize: 31,
        color: C.cobalt,
        bold: part.bold,
        wrap: "none",
        autoFit: "shrinkText",
      },
    );
  }
}

function addCard(slide, card, options = {}) {
  addRect(
    slide,
    { left: card.left, top: card.top, width: card.width, height: card.height },
    {
      name: `${card.name}-surface`,
      fill: options.fill ?? "none",
      line:
        options.line ??
        ({ style: "solid", fill: options.lineColor ?? C.rule, width: 1 }),
    },
  );
  addText(
    slide,
    card.heading,
    {
      left: card.left + 11,
      top: card.top + 12,
      width: card.width - 22,
      height: 24,
    },
    {
      name: `${card.name}-heading`,
      fontSize: options.headingSize ?? 18,
      color: options.headingColor ?? C.cobalt,
      bold: true,
      wrap: "none",
      autoFit: "shrinkText",
    },
  );
  addText(
    slide,
    card.body,
    {
      left: card.left + 11,
      top: card.top + 39,
      width: card.width - 22,
      height: card.height - 48,
    },
    {
      name: `${card.name}-body`,
      fontSize: options.bodySize ?? 12.5,
      color: options.bodyColor ?? C.graphite,
      lineSpacing: 1.16,
      autoFit: "shrinkText",
    },
  );
}

function addNode(slide, name, left, top, label) {
  const node = addRect(
    slide,
    { left, top, width: 80, height: 80 },
    {
      name: `${name}-circle`,
      geometry: "ellipse",
      fill: C.paper,
      line: { style: "solid", fill: C.gray, width: 1 },
    },
  );
  addText(
    slide,
    label,
    { left: left + 8, top: top + 23, width: 64, height: 35 },
    {
      name: `${name}-glyph`,
      fontSize: 25,
      color: C.black,
      bold: true,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );
  return node;
}

function addCover(presentation) {
  const slide = addBaseSlide(presentation, "cover");
  addText(
    slide,
    "Project",
    { left: 330, top: 209, width: 300, height: 68 },
    {
      name: "cover-project-name",
      fontSize: 52,
      color: C.cobalt,
      bold: true,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );
  addText(
    slide,
    "한 줄 서비스 설명",
    { left: 280, top: 294, width: 400, height: 50 },
    {
      name: "cover-subtitle",
      fontSize: 32,
      color: C.graphite,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );
  addText(
    slide,
    "Presented by",
    { left: 50, top: 438, width: 170, height: 25 },
    {
      name: "cover-presented-by",
      fontSize: 18,
      color: C.cobalt,
      bold: true,
      wrap: "none",
    },
  );
  addText(
    slide,
    "이름 · 직책",
    { left: 50, top: 468, width: 180, height: 26 },
    {
      name: "cover-presenter",
      fontSize: 18,
      color: C.cobalt,
      wrap: "none",
    },
  );
}

function addProblems(presentation) {
  const slide = addBaseSlide(presentation, "problems");
  addSplitTitle(slide, [
    { text: "Our", left: 50, width: 61, bold: false, name: "title-prefix" },
    {
      text: "Problems",
      left: 112,
      width: 175,
      bold: true,
      name: "title-keyword",
    },
  ]);
  const cards = [
    {
      name: "problem-1",
      left: 50,
      top: 197,
      width: 279,
      height: 98,
      heading: "낮은 핵심 기능 활용도",
      body: "사용자는 기능을 알고 있어도 실제 상황에서 언제 활용해야 할지 자주 놓칩니다.",
    },
    {
      name: "problem-2",
      left: 340,
      top: 197,
      width: 279,
      height: 98,
      heading: "너무 많은 선택지",
      body: "종류가 지나치게 많으면 비교와 판단이 어려워져 시작 자체를 미루게 됩니다.",
    },
    {
      name: "problem-3",
      left: 630,
      top: 197,
      width: 280,
      height: 98,
      heading: "현재 상태를 알기 어려움",
      body: "사용자가 스스로 수준과 진행 상태를 객관적으로 파악하기 어렵습니다.",
    },
  ];
  cards.forEach((card) => addCard(slide, card));
}

function addSolutions(presentation) {
  const slide = addBaseSlide(presentation, "solutions");
  addSplitTitle(slide, [
    { text: "Our", left: 50, width: 61, bold: false, name: "title-prefix" },
    {
      text: "Solution",
      left: 112,
      width: 170,
      bold: true,
      name: "title-keyword",
    },
  ]);
  const cards = [
    {
      name: "solution-1",
      left: 50,
      top: 198,
      width: 279,
      height: 128,
      heading: "상황에 맞춘 기능 추천",
      body: "자주 막히는 순간을 먼저 찾아 필요한 기능을 바로 제안합니다. 사용자는 복잡한 탐색 없이 다음 행동을 선택합니다.",
    },
    {
      name: "solution-2",
      left: 340,
      top: 198,
      width: 279,
      height: 128,
      heading: "단순한 구독 경험",
      body: "핵심 기능과 콘텐츠를 한 흐름에 묶어 반복 이용을 쉽게 만듭니다. 진입 장벽은 낮추고 효용은 분명하게 보여줍니다.",
    },
    {
      name: "solution-3",
      left: 630,
      top: 198,
      width: 280,
      height: 128,
      heading: "직관적인 성과 데이터",
      body: "점수 하나보다 변화와 비교가 보이는 통계를 제공합니다. 사용자는 자신의 현재 상태와 다음 목표를 바로 이해합니다.",
    },
  ];
  cards.forEach((card) =>
    addCard(slide, card, {
      fill: C.indigo,
      line: { style: "solid", fill: C.indigo, width: 0 },
      headingColor: C.paper,
      bodyColor: C.paper,
    }),
  );
}

function addProduct(presentation) {
  const slide = addBaseSlide(presentation, "product");
  addSingleTitle(slide, "Product");

  const left = addNode(slide, "product-input", 123, 213, "01");
  const center = addNode(slide, "product-core", 440, 213, "02");
  const top = addNode(slide, "product-output-a", 742, 41, "A");
  const middle = addNode(slide, "product-output-b", 742, 213, "B");
  const bottom = addNode(slide, "product-output-c", 742, 388, "C");

  slide.shapes.connect(left, center, {
    kind: "straight",
    fromSide: "right",
    toSide: "left",
    line: { style: "solid", fill: C.black, width: 2 },
  });
  [top, middle, bottom].forEach((target) => {
    slide.shapes.connect(center, target, {
      kind: "straight",
      fromSide: "right",
      toSide: "left",
      line: { style: "solid", fill: C.black, width: 2 },
      tail: { type: "arrow", width: "med", length: "med" },
    });
  });

  const labels = [
    ["문제 선택", 96, 306, 134, "product-input-label"],
    ["핵심 실행", 413, 306, 134, "product-core-label"],
    ["결과 A", 696, 131, 172, "product-output-a-label"],
    ["결과 B", 696, 306, 172, "product-output-b-label"],
    ["결과 C", 696, 475, 172, "product-output-c-label"],
  ];
  labels.forEach(([text, leftPos, topPos, width, name]) => {
    addText(
      slide,
      text,
      { left: leftPos, top: topPos, width, height: 28 },
      {
        name,
        fontSize: 20,
        color: C.indigo,
        bold: true,
        alignment: "center",
        wrap: "none",
      },
    );
  });
}

function addBusinessModel(presentation) {
  const slide = addBaseSlide(presentation, "business-model");
  addSplitTitle(slide, [
    {
      text: "Business",
      left: 50,
      width: 132,
      bold: true,
      name: "title-keyword",
    },
    { text: "Model", left: 183, width: 115, bold: false, name: "title-suffix" },
  ]);

  addText(
    slide,
    "무료",
    { left: 248, top: 184, width: 138, height: 66 },
    {
      name: "free-label",
      fontSize: 52,
      color: C.cobalt,
      bold: true,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );
  addText(
    slide,
    "→",
    { left: 445, top: 226, width: 70, height: 58 },
    {
      name: "conversion-arrow",
      fontSize: 47,
      color: C.black,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );
  addRect(
    slide,
    { left: 584, top: 154, width: 120, height: 120 },
    {
      name: "paid-symbol-circle",
      geometry: "ellipse",
      fill: C.cobalt,
      line: { style: "solid", fill: C.cobalt, width: 0 },
    },
  );
  addText(
    slide,
    "$",
    { left: 596, top: 169, width: 96, height: 87 },
    {
      name: "paid-currency",
      fontSize: 61,
      color: C.paper,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );

  addText(
    slide,
    "주요 기능 무료 이용",
    { left: 208, top: 294, width: 214, height: 28 },
    {
      name: "free-subheading",
      fontSize: 20,
      color: C.ink,
      bold: true,
      alignment: "center",
      wrap: "none",
    },
  );
  addText(
    slide,
    "핵심 기능과 기본 콘텐츠를\n부담 없이 사용할 수 있습니다",
    { left: 204, top: 339, width: 222, height: 54 },
    {
      name: "free-body",
      fontSize: 20,
      color: C.ink,
      bold: true,
      alignment: "center",
      lineSpacing: 1.15,
    },
  );
  addText(
    slide,
    "프리미엄 5,000원 / 월",
    { left: 538, top: 294, width: 252, height: 28 },
    {
      name: "paid-subheading",
      fontSize: 20,
      color: C.ink,
      bold: true,
      alignment: "center",
      wrap: "none",
    },
  );
  addText(
    slide,
    "유료 콘텐츠와 확장 기능을\n더 풍부하게 이용할 수 있습니다",
    { left: 536, top: 339, width: 256, height: 54 },
    {
      name: "paid-body",
      fontSize: 20,
      color: C.ink,
      bold: true,
      alignment: "center",
      lineSpacing: 1.15,
    },
  );
}

function addMarketSize(presentation) {
  const slide = addBaseSlide(presentation, "market-size");
  addSplitTitle(slide, [
    {
      text: "Market",
      left: 50,
      width: 113,
      bold: true,
      name: "title-keyword",
    },
    { text: "Size", left: 164, width: 78, bold: false, name: "title-suffix" },
  ]);

  addRect(
    slide,
    { left: 313, top: 127, width: 334, height: 334 },
    {
      name: "market-perimeter",
      geometry: "ellipse",
      fill: "none",
      line: { style: "dotted", fill: C.cobalt, width: 4 },
    },
  );

  slide.charts.add("pie", {
    position: { left: 342, top: 157, width: 276, height: 276 },
    categories: ["Segment A", "Segment B", "Segment C"],
    series: [
      {
        name: "Market share",
        values: [35, 40, 25],
        line: { style: "solid", fill: C.paper, width: 4 },
        points: [
          {
            idx: 0,
            fill: C.violetLight,
            line: { style: "solid", fill: C.paper, width: 4 },
          },
          {
            idx: 1,
            fill: C.indigo,
            line: { style: "solid", fill: C.paper, width: 4 },
          },
          {
            idx: 2,
            fill: C.violetMid,
            line: { style: "solid", fill: C.paper, width: 4 },
          },
        ],
      },
    ],
    pieOptions: { firstSliceAngle: 324 },
    hasLegend: false,
    dataLabels: {
      showValue: false,
      showSeriesName: false,
      showCategoryName: false,
    },
    chartFill: "none",
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaFill: "none",
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });

  addLine(slide, 120, 283, 238, 0, {
    name: "market-left-leader",
    color: C.cobaltSoft,
    weight: 1,
  });
  addText(
    slide,
    "41만 명",
    { left: 121, top: 267, width: 136, height: 38 },
    {
      name: "market-left-metric",
      fontSize: 31,
      color: "#5459C4",
      bold: true,
      wrap: "none",
    },
  );
  addText(
    slide,
    "핵심 고객군 A",
    { left: 122, top: 307, width: 162, height: 24 },
    {
      name: "market-left-label",
      fontSize: 16,
      color: C.graphite,
      wrap: "none",
    },
  );

  addLine(slide, 546, 181, 167, 0, {
    name: "market-right-leader",
    color: C.cobaltSoft,
    weight: 1,
  });
  addText(
    slide,
    "44만 명",
    { left: 723, top: 162, width: 132, height: 38 },
    {
      name: "market-right-metric",
      fontSize: 31,
      color: C.cobaltSoft,
      bold: true,
      wrap: "none",
    },
  );
  addText(
    slide,
    "핵심 고객군 B",
    { left: 724, top: 204, width: 162, height: 24 },
    {
      name: "market-right-label",
      fontSize: 16,
      color: C.graphite,
      wrap: "none",
    },
  );

  addText(
    slide,
    "50만 명+",
    { left: 420, top: 338, width: 190, height: 42 },
    {
      name: "market-center-metric",
      fontSize: 31,
      color: C.paper,
      bold: true,
      alignment: "center",
      wrap: "none",
    },
  );
  addText(
    slide,
    "확장 고객군 C",
    { left: 430, top: 378, width: 180, height: 24 },
    {
      name: "market-center-label",
      fontSize: 15,
      color: C.paper,
      alignment: "center",
      wrap: "none",
    },
  );
}

function addFunding(presentation) {
  const slide = addBaseSlide(presentation, "funding");
  addSingleTitle(slide, "Investment Needed", { width: 390 });

  addRect(
    slide,
    { left: 50, top: 159, width: 860, height: 79 },
    {
      name: "funding-total-bar",
      fill: C.cobalt,
      line: { style: "solid", fill: C.cobalt, width: 0 },
    },
  );
  addText(
    slide,
    "50,000,000 원",
    { left: 250, top: 175, width: 460, height: 48 },
    {
      name: "funding-total",
      fontSize: 35,
      color: C.paper,
      bold: true,
      alignment: "center",
      verticalAlignment: "middle",
      wrap: "none",
    },
  );

  const segments = [
    {
      name: "fixed-costs",
      left: 50,
      width: 367,
      percent: "45%",
      heading: "고정지출",
      note: "임대료 · 인건비 · 서버비",
    },
    {
      name: "marketing",
      left: 417,
      width: 252,
      percent: "30%",
      heading: "광고비",
      note: "검색 · 소셜 · 영상 광고",
    },
    {
      name: "content-rights",
      left: 669,
      width: 241,
      percent: "25%",
      heading: "콘텐츠 저작권",
      note: "유료 콘텐츠 이용료",
    },
  ];

  segments.forEach((segment) => {
    addRect(
      slide,
      { left: segment.left, top: 247, width: segment.width, height: 106 },
      {
        name: `${segment.name}-allocation-box`,
        fill: C.paper,
        line: { style: "dashed", fill: C.cobalt, width: 3 },
      },
    );
    addText(
      slide,
      segment.percent,
      { left: segment.left, top: 284, width: segment.width, height: 30 },
      {
        name: `${segment.name}-percent`,
        fontSize: 21,
        color: C.cobalt,
        bold: true,
        alignment: "center",
        wrap: "none",
      },
    );
    addText(
      slide,
      segment.heading,
      { left: segment.left, top: 369, width: segment.width, height: 28 },
      {
        name: `${segment.name}-heading`,
        fontSize: 17,
        color: C.cobalt,
        bold: true,
        alignment: "center",
        wrap: "none",
      },
    );
    addText(
      slide,
      segment.note,
      { left: segment.left, top: 398, width: segment.width, height: 22 },
      {
        name: `${segment.name}-note`,
        fontSize: 12,
        color: C.gray,
        alignment: "center",
        wrap: "none",
      },
    );
  });
}

function addTeam(presentation) {
  const slide = addBaseSlide(presentation, "team");
  addSplitTitle(slide, [
    { text: "Our", left: 50, width: 61, bold: false, name: "title-prefix" },
    { text: "Team", left: 112, width: 112, bold: true, name: "title-keyword" },
  ]);

  const members = [
    { left: 135, geometry: "rect", number: "01", name: "멤버 1", role: "CEO / Co-Founder" },
    { left: 307, geometry: "ellipse", number: "02", name: "멤버 2", role: "CTO / Co-Founder" },
    { left: 469, geometry: "ellipse", number: "03", name: "멤버 3", role: "Designer" },
    { left: 617, geometry: "ellipse", number: "04", name: "멤버 4", role: "Developer" },
    { left: 769, geometry: "ellipse", number: "05", name: "멤버 5", role: "Developer" },
  ];

  members.forEach((member, index) => {
    addRect(
      slide,
      { left: member.left, top: 109, width: 100, height: 100 },
      {
        name: `team-photo-${index + 1}`,
        geometry: member.geometry,
        fill: index % 2 === 0 ? C.paper : "#E4E9FF",
        line: { style: "solid", fill: C.timeline, width: 1 },
      },
    );
    addText(
      slide,
      member.number,
      { left: member.left + 10, top: 141, width: 80, height: 38 },
      {
        name: `team-photo-label-${index + 1}`,
        fontSize: 24,
        color: C.cobalt,
        bold: true,
        alignment: "center",
        verticalAlignment: "middle",
        wrap: "none",
      },
    );
    addText(
      slide,
      member.name,
      { left: member.left - 18, top: 215, width: 136, height: 28 },
      {
        name: `team-name-${index + 1}`,
        fontSize: 20,
        color: C.graphite,
        alignment: "center",
        wrap: "none",
      },
    );
    addText(
      slide,
      member.role,
      { left: member.left - 25, top: 246, width: 150, height: 24 },
      {
        name: `team-role-${index + 1}`,
        fontSize: 15.5,
        color: C.indigo,
        alignment: "center",
        wrap: "none",
      },
    );
  });

  addText(
    slide,
    "팀의 핵심 역량과 함께 해결할 문제를 한 문장으로 정리합니다.",
    { left: 115, top: 323, width: 520, height: 32 },
    {
      name: "team-capability",
      fontSize: 18,
      color: C.ink,
      wrap: "none",
    },
  );
}

function addRoadmap(presentation) {
  const slide = addBaseSlide(presentation, "roadmap");
  addSingleTitle(slide, "Road Map", { width: 250 });
  addLine(slide, 0, 316, 865, 0, {
    name: "roadmap-baseline",
    color: C.timeline,
    weight: 3,
  });

  const milestones = [
    ["M1", "Beta launch", "첫 사용자 확보\n기본 기능 검증"],
    ["M2", "Pilot 1", "핵심 지표 확인\n피드백 반영"],
    ["M3", "Official launch", "서비스 공개\n사용자 확대"],
    ["M4", "Pilot 2", "콘텐츠 확장\n재방문 개선"],
    ["M5", "Feature pack", "신규 기능 추가\n품질 고도화"],
    ["M6", "Pilot 3", "고객군 확대\n성과 측정"],
    ["M7", "Paid tier", "유료 기능 출시\n전환 검증"],
    ["M8", "Pilot 4", "상품성 검증\n운영 안정화"],
    ["M9", "Next scale", "다음 시장 준비\n확장 계획 수립"],
  ];
  const xs = [57, 152, 247, 342, 437, 532, 627, 722, 817];

  milestones.forEach(([date, heading, body], index) => {
    const x = xs[index];
    const upper = index % 2 === 1;
    addLine(slide, x, upper ? 181 : 316, 0, upper ? 135 : 120, {
      name: `roadmap-stem-${index + 1}`,
      color: C.cobaltSoft,
      weight: 1,
    });
    addRect(
      slide,
      { left: x - 12, top: 304, width: 24, height: 24 },
      {
        name: `roadmap-halo-${index + 1}`,
        geometry: "ellipse",
        fill: C.paper,
        line: { style: "solid", fill: C.timeline, width: 1 },
      },
    );
    addRect(
      slide,
      { left: x - 5, top: 311, width: 10, height: 10 },
      {
        name: `roadmap-node-${index + 1}`,
        geometry: "ellipse",
        fill: C.cobalt,
        line: { style: "solid", fill: C.cobalt, width: 0 },
      },
    );

    const cardLeft = x + 8;
    if (upper) {
      addText(
        slide,
        date,
        { left: cardLeft, top: 286, width: 80, height: 14 },
        {
          name: `roadmap-date-${index + 1}`,
          fontSize: 7.5,
          color: C.cobalt,
          bold: true,
          wrap: "none",
        },
      );
      addText(
        slide,
        heading,
        { left: cardLeft, top: 182, width: 88, height: 18 },
        {
          name: `roadmap-heading-${index + 1}`,
          fontSize: 10,
          color: C.cobalt,
          bold: true,
          wrap: "none",
          autoFit: "shrinkText",
        },
      );
      addText(
        slide,
        body,
        { left: cardLeft, top: 206, width: 88, height: 54 },
        {
          name: `roadmap-body-${index + 1}`,
          fontSize: 7.5,
          color: C.gray,
          lineSpacing: 1.15,
        },
      );
    } else {
      addText(
        slide,
        date,
        { left: x - 21, top: 286, width: 62, height: 14 },
        {
          name: `roadmap-date-${index + 1}`,
          fontSize: 7.5,
          color: C.cobalt,
          bold: true,
          alignment: "center",
          wrap: "none",
        },
      );
      addText(
        slide,
        heading,
        { left: cardLeft, top: 373, width: 88, height: 18 },
        {
          name: `roadmap-heading-${index + 1}`,
          fontSize: 10,
          color: C.cobalt,
          bold: true,
          wrap: "none",
          autoFit: "shrinkText",
        },
      );
      addText(
        slide,
        body,
        { left: cardLeft, top: 397, width: 88, height: 54 },
        {
          name: `roadmap-body-${index + 1}`,
          fontSize: 7.5,
          color: C.gray,
          lineSpacing: 1.15,
        },
      );
    }
  });
}

async function writeBlob(filePath, blob) {
  await fs.mkdir(path.dirname(filePath), { recursive: true });
  await fs.writeFile(filePath, new Uint8Array(await blob.arrayBuffer()));
}

async function exportEvidence(presentation, options) {
  if (options.previewDir) {
    await fs.mkdir(options.previewDir, { recursive: true });
  }
  if (options.layoutDir) {
    await fs.mkdir(options.layoutDir, { recursive: true });
  }

  for (const [index, slide] of presentation.slides.items.entries()) {
    const stem = `slide-${String(index + 1).padStart(2, "0")}`;
    if (options.previewDir) {
      await writeBlob(
        path.join(options.previewDir, `${stem}.png`),
        await presentation.export({ slide, format: "png", scale: 1 }),
      );
    }
    if (options.layoutDir) {
      const layout = await slide.export({ format: "layout" });
      await fs.writeFile(
        path.join(options.layoutDir, `${stem}.layout.json`),
        await layout.text(),
      );
    }
  }

  if (options.montage) {
    await writeBlob(
      options.montage,
      await presentation.export({ format: "webp", montage: true, scale: 1 }),
    );
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.out || typeof args.out !== "string") {
    throw new Error("Missing required --out /absolute/path/to/template.pptx");
  }

  const out = path.resolve(args.out);
  const presentation = Presentation.create({ slideSize: SIZE });
  addCover(presentation);
  addProblems(presentation);
  addSolutions(presentation);
  addProduct(presentation);
  addBusinessModel(presentation);
  addMarketSize(presentation);
  addFunding(presentation);
  addTeam(presentation);
  addRoadmap(presentation);

  await exportEvidence(presentation, {
    previewDir:
      typeof args["preview-dir"] === "string"
        ? path.resolve(args["preview-dir"])
        : undefined,
    layoutDir:
      typeof args["layout-dir"] === "string"
        ? path.resolve(args["layout-dir"])
        : undefined,
    montage:
      typeof args.montage === "string" ? path.resolve(args.montage) : undefined,
  });

  await fs.mkdir(path.dirname(out), { recursive: true });
  const pptx = await PresentationFile.exportPptx(presentation);
  await pptx.save(out);
  process.stdout.write(`${out}\n`);
}

main().catch((error) => {
  process.stderr.write(`${error.stack ?? error.message}\n`);
  process.exitCode = 1;
});
