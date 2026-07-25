import fs from "node:fs/promises";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const inputPath = "C:/Users/SAKSHI/Documents/ecommerce_analytics_project/women_shirts.xlsx";
const qaDir = "C:/Users/SAKSHI/Documents/ecommerce_analytics_project/outputs/women_shirts_qa";
await fs.mkdir(qaDir, { recursive: true });
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));

const overview = await workbook.inspect({
  kind: "workbook,sheet,table",
  maxChars: 10000,
  tableMaxRows: 8,
  tableMaxCols: 30,
  tableMaxCellChars: 100,
});
console.log(overview.ndjson);

for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange();
  console.log(`USED ${sheet.name}: ${used?.address ?? "none"}`);
  if (!used) continue;
  const endCol = used.address.split(":").at(-1).replace(/[0-9]/g, "");
  const endRow = Math.min(25, Number(used.address.split(":").at(-1).replace(/[^0-9]/g, "")));
  const preview = await workbook.render({ sheetName: sheet.name, range: `A1:${endCol}${endRow}`, scale: 1, format: "png" });
  await fs.writeFile(`${qaDir}/${sheet.name.replace(/[^a-z0-9_-]/gi, "_")}.png`, new Uint8Array(await preview.arrayBuffer()));
}
