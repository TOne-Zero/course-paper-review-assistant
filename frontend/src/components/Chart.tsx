import { useEffect, useRef, useState } from 'react';
import * as echarts from 'echarts/core';
import { BarChart, RadarChart, PieChart } from 'echarts/charts';
import { AriaComponent, GridComponent, TooltipComponent } from 'echarts/components';
import { SVGRenderer } from 'echarts/renderers';
import type { EChartsOption } from 'echarts';
import { DIMENSIONS } from '../model';

echarts.use([BarChart, RadarChart, PieChart, AriaComponent, GridComponent, TooltipComponent, SVGRenderer]);
const serif = 'Noto Serif SC Variable, SimSun, serif';
const ink = '#111111', accent = '#A31F34', muted = '#666666', line = '#E5E7EB';

export function useReducedMotion() {
  const [reduced, setReduced] = useState(() => matchMedia('(prefers-reduced-motion: reduce)').matches);
  useEffect(() => {
    const media = matchMedia('(prefers-reduced-motion: reduce)');
    const change = () => setReduced(media.matches);
    media.addEventListener('change', change);
    return () => media.removeEventListener('change', change);
  }, []);
  return reduced;
}

export function Chart({ option, label, className = '' }: { option: EChartsOption; label: string; className?: string }) {
  const element = useRef<HTMLDivElement>(null);
  const instance = useRef<echarts.ECharts>();
  const reduced = useReducedMotion();
  useEffect(() => {
    if (!element.current) return;
    const chart = echarts.init(element.current, undefined, { renderer: 'svg' });
    instance.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element.current);
    return () => { observer.disconnect(); chart.dispose(); instance.current = undefined; };
  }, []);
  useEffect(() => {
    instance.current?.setOption({ ...option, backgroundColor: 'transparent', animation: !reduced,
      animationDuration: 450, animationDurationUpdate: 250,
      aria: { enabled: true, label: { description: label } } }, { notMerge: true });
  }, [option, label, reduced]);
  return <div ref={element} className={`min-w-0 ${className}`} role="img" aria-label={label} />;
}

export function histogramOption(bins: number[]): EChartsOption {
  return {
    grid: { left: 22, right: 12, top: 32, bottom: 36, containLabel: false },
    textStyle: { fontFamily: serif, color: ink },
    tooltip: { trigger: 'axis', backgroundColor: '#FFFFFF', borderColor: line, borderWidth: 1, textStyle: { color: ink, fontSize: 12 }, axisPointer: { type: 'none' } },
    xAxis: { type: 'category', data: ['60 以下', '60—69', '70—79', '80—89', '90—100'], axisTick: { show: false },
      axisLine: { lineStyle: { color: line, width: 1 } }, axisLabel: { color: muted, fontFamily: serif, fontSize: 11, margin: 14, interval: 0 } },
    yAxis: { type: 'value', show: false, minInterval: 1, max: Math.max(...bins, 2) + 1 },
    series: [{ type: 'bar', data: bins.map((value, index) => ({ value, itemStyle: { color: index === 3 ? accent : ink } })), barWidth: '28%',
      label: { show: true, position: 'top', color: ink, fontFamily: serif, fontSize: 14, distance: 12 }, emphasis: { itemStyle: { color: accent } } }],
  };
}

export function radarOption(values: (number|null)[], single = false, names=DIMENSIONS): EChartsOption {
  return {
    textStyle: { fontFamily: serif, color: ink },
    tooltip: { trigger: 'item', backgroundColor: '#FFFFFF', borderColor: line, textStyle: { color: ink, fontSize: 12 } },
    radar: { indicator: names.map(name => ({ name, max: 100 })), center: ['50%', '51%'], radius: '65%',
      splitNumber: 3, shape: 'polygon', axisNameGap: 10,
      axisName: { color: muted, fontFamily: serif, fontSize: 11 },
      splitArea: { show: false }, splitLine: { lineStyle: { color: '#E8E8E8', width: 0.65 } },
      axisLine: { lineStyle: { color: '#D9D9D9', width: 0.65 } } },
    series: [{ type: 'radar', symbol: 'circle', symbolSize: 3,
      lineStyle: { color: accent, width: 1.2 }, itemStyle: { color: accent }, areaStyle: { color: 'rgba(163,31,52,0.035)' },
      data: [{ value: values.map(value => value===null?null:+value.toFixed(1)), name: single ? '单篇维度得分率（%）' : '维度平均得分率（%）' }] }],
  };
}

const weightColors = ['#A31F34', '#111111', '#333333', '#555555', '#777777', '#888888', '#949494'];
export function weightOption(weights: number[], names=DIMENSIONS, dividerWidth=2): EChartsOption {
  return { tooltip: { trigger: 'item', backgroundColor: '#FFFFFF', borderColor: line, textStyle: { color: ink, fontSize: 12 }, formatter: '{b}：{c} 分' },
    series: [{ type: 'pie', radius: ['77%', '81%'], center: ['50%', '50%'], startAngle: 90, clockwise: true,
      label: { show: false }, labelLine: { show: false }, itemStyle: { borderColor: '#FFFFFF', borderWidth: dividerWidth },
      emphasis: { scale: false }, data: weights.map((value, i) => ({ name: names[i], value, itemStyle: { color: weightColors[i%weightColors.length] } })) }],
  };
}
