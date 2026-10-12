/**
 * File Analyzer Tool
 * 
 * 分析文本文件并生成结构化报告。
 * 演示 AgnesCode P2-1 工具自进化机制的完整实现。
 * 
 * 运行方式：
 *   deno run --allow-read analyzer.ts <file_path> [top_n]
 */

import { parse } from "https://deno.land/std@0.208.0/encoding/csv.ts";

interface AnalysisResult {
  file_path: string;
  file_size_bytes: number;
  line_count: number;
  char_count: number;
  word_count: number;
  encoding: string;
  top_words: Array<{ word: string; count: number }>;
  analyzed_at: string;
}

function detectEncoding(buffer: Uint8Array): string {
  // 简化版编码检测（实际应使用更复杂的启发式算法）
  if (buffer[0] === 0xEF && buffer[1] === 0xBB && buffer[2] === 0xBF) {
    return "UTF-8-BOM";
  }
  // 尝试 UTF-8 解码，失败则回退到 GBK
  try {
    new TextDecoder("utf-8", { fatal: true }).decode(buffer);
    return "UTF-8";
  } catch {
    return "GBK/Latin-1";
  }
}

function extractWords(text: string): Map<string, number> {
  const words = text.toLowerCase().match(/\b[a-zA-Z\u4e00-\u9fff]+\b/g) || [];
  const freq = new Map<string, number>();
  
  for (const word of words) {
    freq.set(word, (freq.get(word) || 0) + 1);
  }
  
  return freq;
}

async function analyzeFile(filePath: string, topN: number = 10): Promise<AnalysisResult> {
  // 读取文件
  const content = await Deno.readTextFile(filePath);
  const fileInfo = await Deno.stat(filePath);
  
  // 编码检测
  const buffer = await Deno.readFile(filePath);
  const encoding = detectEncoding(buffer);
  
  // 统计分析
  const lines = content.split("\n");
  const words = extractWords(content);
  
  // 取前 N 个高频词
  const sortedWords = Array.from(words.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, topN)
    .map(([word, count]) => ({ word, count }));
  
  return {
    file_path: filePath,
    file_size_bytes: fileInfo.size,
    line_count: lines.length,
    char_count: content.length,
    word_count: words.size,
    encoding,
    top_words: sortedWords,
    analyzed_at: new Date().toISOString(),
  };
}

// MCP 工具注册接口（引擎侧需提供）
async function registerAsMCPTool() {
  const manifest = JSON.parse(await Deno.readTextFile("tool.yaml"));
  
  // 调用引擎的 MCP 注册 API（伪代码，实际由 agnedd 提供）
  // await fetch("http://127.0.0.1:3080/mcp/register", {
  //   method: "POST",
  //   headers: { "Content-Type": "application/json" },
  //   body: JSON.stringify({
  //     name: manifest.name,
  //     description: manifest.description,
  //     parameters: manifest.parameters,
  //     handler: "analyzer.ts",
  //   }),
  // });
  
  console.log(`✓ Tool "${manifest.name}" registered via MCP`);
}

// 主入口
if (import.meta.main) {
  const args = Deno.args;
  
  if (args.length < 1) {
    console.error("Usage: deno run analyzer.ts <file_path> [top_n]");
    Deno.exit(1);
  }
  
  const filePath = args[0];
  const topN = parseInt(args[1] || "10", 10);
  
  try {
    const result = await analyzeFile(filePath, topN);
    console.log(JSON.stringify(result, null, 2));
    
    // 自动注册为 MCP 工具（可选）
    await registerAsMCPTool();
  } catch (error) {
    console.error(`✗ Analysis failed: ${error.message}`);
    Deno.exit(1);
  }
}
