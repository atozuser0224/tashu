import { useMemo, type CSSProperties } from 'react';
import { Platform, StyleSheet, Text, View, type DimensionValue } from 'react-native';
import { WebView } from 'react-native-webview';

import { colors } from '../theme';

export type MapPoint = {
  lat: number;
  lng: number;
  label?: string;
  kind?: 'driver' | 'pickup' | 'dropoff';
};

export type MapRoute = {
  id: string;
  color?: string;
  coordinates: Array<{ lat: number; lng: number }>;
};

type Props = {
  tmapKey: string;
  routes: MapRoute[];
  markers?: MapPoint[];
  height?: DimensionValue;
};

const iframeStyle: CSSProperties = {
  width: '100%',
  height: '100%',
  display: 'block',
  border: 0,
  backgroundColor: '#E8E8E8',
};

function escapeHtmlJson(value: unknown) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

function buildHtml(tmapKey: string, routes: MapRoute[], markers: MapPoint[]) {
  const allPoints = [
    ...routes.flatMap((route) => route.coordinates),
    ...markers,
  ].filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng));
  const center = allPoints[0] ?? { lat: 36.3504, lng: 127.3845 };
  const sdkUrl = `https://apis.openapi.sk.com/tmap/jsv2?version=1&appKey=${encodeURIComponent(tmapKey)}`;

  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no" />
  <style>
    html,body,#map{width:100%;height:100%;margin:0;overflow:hidden;background:#e8e8e8;font-family:Archivo,system-ui,sans-serif}
    #map{animation:rg-zoomin .75s cubic-bezier(.22,.61,.36,1) both;transform-origin:50% 46%}
    #map *{box-sizing:content-box}
    #status{position:absolute;z-index:30;left:16px;right:16px;top:16px;padding:11px 13px;border-radius:12px;background:rgba(32,30,29,.88);color:#fff;font:700 12px/1.45 Archivo,system-ui;display:none}
    @keyframes rg-zoomin{0%{transform:scale(1.18)}100%{transform:scale(1)}}
    @keyframes rg-pulse{0%{transform:scale(.6);opacity:.55}72%{transform:scale(2.8);opacity:0}100%{opacity:0}}

    .mk-wrap{position:relative;width:30px;height:30px;transform:translate(-50%,-50%)}
    .mk-ring{position:absolute;inset:0;width:30px;height:30px;border-radius:50%;background:var(--c);opacity:.4;animation:rg-pulse 2s ease-out infinite}
    .mk-dot{position:absolute;inset:0;width:30px;height:30px;border-radius:50%;background:var(--c);border:3px solid #fff;box-shadow:0 3px 12px rgba(0,0,0,.4);display:flex;align-items:center;justify-content:center;z-index:2}
    .mk-dot svg{width:16px;height:16px;display:block}
    .mk-label{position:absolute;top:39px;left:50%;transform:translateX(-50%);white-space:nowrap;background:#201e1d;color:#fff;font-size:10px;font-weight:800;padding:4px 8px;border-radius:8px;letter-spacing:-.02em;box-shadow:0 2px 8px rgba(0,0,0,.25);z-index:3}
    .mk-label:after{content:"";position:absolute;left:50%;top:-4px;transform:translateX(-50%);border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:4px solid #201e1d}
    .route-bubble{display:inline-flex;align-items:center;justify-content:center;transform:translate(-50%,-125%);background:#fff;padding:9px 17px;border-radius:16px;font-size:14px;font-weight:800;color:#201e1d;letter-spacing:-.02em;box-shadow:0 8px 22px rgba(0,0,0,.18);white-space:nowrap;position:relative;line-height:1}
    .route-bubble:after{content:"";position:absolute;left:50%;bottom:-6px;transform:translateX(-50%);border-left:7px solid transparent;border-right:7px solid transparent;border-top:7px solid #fff}
  </style>
  <script src="${sdkUrl}"></script>
</head>
<body>
  <div id="map"></div><div id="status"></div>
  <script>
    const routes = ${escapeHtmlJson(routes)};
    const markers = ${escapeHtmlJson(markers)};
    const center = ${escapeHtmlJson(center)};
    const status = document.getElementById('status');
    const personIcon = '<svg viewBox="0 0 24 24" fill="#fff"><circle cx="12" cy="7.5" r="3.6"/><path d="M5.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6z"/></svg>';
    const pickupIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M3 8 12 4l9 4-9 4z"/><path d="M3 8v8l9 4 9-4V8"/><path d="M12 12v8"/></svg>';
    const bikeIcon = '<svg viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="6" cy="17" r="3.4"/><circle cx="18" cy="17" r="3.4"/><path d="M6 17 10 8h5l3 9M10 8l2 5h6"/></svg>';

    function fail(message){ status.style.display='block'; status.textContent=message; }
    function safeText(value){
      return String(value == null ? '' : value).replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    }
    function markerLabel(marker,index){
      const raw = String(marker.label == null ? '' : marker.label).trim();
      if (marker.kind === 'driver') return raw && raw !== '기사' ? raw : '현재 위치';
      if (marker.kind === 'pickup') return raw && !/^\\d+$/.test(raw) ? raw : '회수 지점';
      if (marker.kind === 'dropoff') return raw && !/^\\d+$/.test(raw) ? raw : '재배치 대여소';
      return raw || String(index + 1);
    }
    function markerHtml(marker,index){
      const color = marker.kind === 'pickup' ? '#1FA35C' : marker.kind === 'dropoff' ? '#F7941D' : '#201e1d';
      const icon = marker.kind === 'pickup' ? pickupIcon : marker.kind === 'dropoff' ? bikeIcon : personIcon;
      return '<div class="mk-wrap" style="--c:'+color+'"><span class="mk-ring"></span><span class="mk-dot">'+icon+'</span><span class="mk-label">'+safeText(markerLabel(marker,index))+'</span></div>';
    }
    function haversine(a,b){
      const rad = Math.PI / 180;
      const dLat = (b.lat-a.lat)*rad;
      const dLng = (b.lng-a.lng)*rad;
      const x = Math.sin(dLat/2)**2 + Math.cos(a.lat*rad)*Math.cos(b.lat*rad)*Math.sin(dLng/2)**2;
      return 6371000 * 2 * Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
    }
    function routeMeters(points){
      let total=0;
      for(let i=1;i<points.length;i+=1) total += haversine(points[i-1],points[i]);
      return total;
    }
    function distanceLabel(points){
      const meters=routeMeters(points);
      return meters >= 1000 ? (meters/1000).toFixed(1)+' km' : Math.max(0,Math.round(meters))+' m';
    }
    function init(){
      try {
        if (!window.Tmapv2) throw new Error('TMAP SDK를 불러오지 못했습니다. 키와 네트워크를 확인하세요.');
        const map = new Tmapv2.Map('map', {
          center:new Tmapv2.LatLng(center.lat,center.lng),
          zoom:16,
          zoomControl:false,
          scrollwheel:true,
        });
        const bounds = new Tmapv2.LatLngBounds();
        let pointCount = 0;

        routes.forEach((route) => {
          const valid = route.coordinates.filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lng));
          const path = valid.map((point) => {
            const latLng = new Tmapv2.LatLng(point.lat,point.lng);
            bounds.extend(latLng);
            pointCount += 1;
            return latLng;
          });
          if (path.length > 1) {
            const color = route.color || '#F7941D';
            new Tmapv2.Polyline({ path, strokeColor:color, strokeWeight:11, strokeOpacity:.3, map });
            new Tmapv2.Polyline({ path, strokeColor:color, strokeWeight:5, strokeOpacity:1, map });
            const middleIndex = Math.floor(path.length / 2);
            new Tmapv2.Marker({
              position:path[middleIndex],
              iconHTML:'<div class="route-bubble">'+distanceLabel(valid)+'</div>',
              map,
            });
          }
        });

        markers.forEach((marker,index) => {
          if (!Number.isFinite(marker.lat) || !Number.isFinite(marker.lng)) return;
          const latLng = new Tmapv2.LatLng(marker.lat,marker.lng);
          bounds.extend(latLng);
          pointCount += 1;
          new Tmapv2.Marker({ position:latLng, iconHTML:markerHtml(marker,index), map });
        });

        if (pointCount > 1) map.fitBounds(bounds, {left:46,right:46,top:132,bottom:220});
        else if (pointCount === 1) { map.setCenter(new Tmapv2.LatLng(center.lat,center.lng)); map.setZoom(16); }
      } catch (error) { fail(error && error.message ? error.message : String(error)); }
    }
    window.addEventListener('load', init);
  </script>
</body></html>`;
}

export function TmapMissionMap({ tmapKey, routes, markers = [], height = 360 }: Props) {
  const html = useMemo(
    () => (tmapKey ? buildHtml(tmapKey, routes, markers) : ''),
    [tmapKey, routes, markers],
  );

  if (!tmapKey) {
    return (
      <View style={[styles.placeholder, { height }]}>
        <View style={styles.routeGlyph}>
          <View style={[styles.dot, styles.greenDot]} />
          <View style={styles.line} />
          <View style={[styles.dot, styles.orangeDot]} />
        </View>
        <Text style={styles.placeholderTitle}>TMAP 키가 필요합니다</Text>
        <Text style={styles.placeholderBody}>
          설정에서 키를 입력하면 기사 재배치 경로가 여기에 표시됩니다.
        </Text>
        <Text style={styles.routeCount}>경로 데이터 {routes.length}개 준비됨</Text>
      </View>
    );
  }

  return (
    <View style={[styles.frame, { height }]}>
      {Platform.OS === 'web' ? (
        <iframe
          title="TMAP 기사 재배치 경로"
          srcDoc={html}
          sandbox="allow-scripts allow-same-origin"
          referrerPolicy="strict-origin-when-cross-origin"
          allow="geolocation 'none'; camera 'none'; microphone 'none'"
          style={iframeStyle}
        />
      ) : (
        <WebView
          originWhitelist={['*']}
          source={{ html, baseUrl: 'https://localhost/' }}
          javaScriptEnabled
          domStorageEnabled={false}
          mixedContentMode="never"
          setSupportMultipleWindows={false}
          style={styles.webview}
        />
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { overflow: 'hidden', backgroundColor: '#E8E8E8' },
  webview: { flex: 1, backgroundColor: '#E8E8E8' },
  placeholder: {
    alignItems: 'center', justifyContent: 'center', paddingHorizontal: 36,
    backgroundColor: '#E8E8E8',
  },
  routeGlyph: { flexDirection: 'row', alignItems: 'center', marginBottom: 22 },
  dot: { width: 20, height: 20, borderRadius: 10, borderWidth: 4, borderColor: colors.paper },
  greenDot: { backgroundColor: '#1FA35C' },
  orangeDot: { backgroundColor: '#F7941D' },
  line: { width: 92, height: 6, backgroundColor: '#201E1D', marginHorizontal: -2 },
  placeholderTitle: { color: '#201E1D', fontSize: 18, fontWeight: '800' },
  placeholderBody: { color: '#7D7979', fontSize: 13, lineHeight: 20, textAlign: 'center', marginTop: 8 },
  routeCount: { marginTop: 16, color: '#178B4C', fontSize: 12, fontWeight: '800' },
});
