import { useEffect } from 'react';
import { StatusBar } from 'expo-status-bar';
import { LinearGradient } from 'expo-linear-gradient';
import { Pressable, StyleSheet, Text } from 'react-native';
import Svg, { Circle, ClipPath, Defs, Ellipse, G, Line, Path, Rect } from 'react-native-svg';

const BRAND = '타슈캐스트';

export function SplashScreen({ onDone }: { onDone: () => void }) {
  useEffect(() => {
    const timer = setTimeout(onDone, 3200);
    return () => clearTimeout(timer);
  }, [onDone]);

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="시작 화면 건너뛰기"
      onPress={onDone}
      style={styles.root}
    >
      <StatusBar style="dark" />
      <LinearGradient
        colors={['#FCA632', '#F7941D', '#EC7C15', '#25A35E']}
        locations={[0, 0.55, 0.74, 1]}
        style={StyleSheet.absoluteFill}
      />
      <Text style={styles.brand}>{BRAND}</Text>
      <DaejeonRideIllustration />
    </Pressable>
  );
}

function DaejeonRideIllustration() {
  return (
    <Svg width={300} height={300} viewBox="0 0 300 300" style={styles.illustration}>
      <Defs>
        <ClipPath id="ridego-landscape-clip">
          <Circle cx={150} cy={150} r={140} />
        </ClipPath>
      </Defs>
      <Circle cx={150} cy={150} r={140} fill="#FFFFFF" />
      <G clipPath="url(#ridego-landscape-clip)">
        <G>
          <Ellipse cx={96} cy={78} rx={26} ry={12} fill="#FBE3C4" />
          <Ellipse cx={120} cy={72} rx={18} ry={12} fill="#FBE3C4" />
        </G>
        <G>
          <Ellipse cx={212} cy={104} rx={20} ry={9} fill="#FCEAD5" />
          <Ellipse cx={230} cy={100} rx={14} ry={9} fill="#FCEAD5" />
        </G>

        <Path d="M110 78 L128 200 L92 200 Z" fill="#F4A548" />
        <Path d="M110 78 L110 200 L92 200 Z" fill="#E8892A" />
        <Rect x={78} y={132} width={70} height={24} rx={12} fill="#FBC178" />
        {[92, 104, 116, 128, 140].map((x) => (
          <Line key={x} x1={x} y1={138} x2={x} y2={150} stroke="#F3982F" strokeWidth={4} />
        ))}

        <Path d="M150 196 Q200 118 250 196" fill="none" stroke="#E8892A" strokeWidth={9} />
        <Path d="M188 196 Q244 112 298 196" fill="none" stroke="#C96E12" strokeWidth={9} />
        {[168, 188, 212, 236].map((x, index) => (
          <Line
            key={x}
            x1={x}
            y1={index === 0 ? 176 : index === 1 || index === 3 ? 158 : 150}
            x2={x}
            y2={196}
            stroke="#F4A548"
            strokeWidth={2.4}
            opacity={0.9}
          />
        ))}
        <Rect x={150} y={192} width={150} height={6} fill="#D97C1C" />
        <Rect x={164} y={196} width={10} height={16} fill="#CE7414" />
        <Rect x={246} y={196} width={10} height={16} fill="#CE7414" />

        <Ellipse cx={150} cy={214} rx={128} ry={30} fill="#EF9A38" />
        <Path d="M22 210 Q150 190 278 210" fill="none" stroke="#F6B268" strokeWidth={6} />

        <G>
          <Rect x={52} y={186} width={5} height={26} fill="#C96E12" />
          <Path d="M54 158 L40 192 L69 192 Z" fill="#EC8A24" />
          <Path d="M54 168 L44 192 L65 192 Z" fill="#D97C1C" />
        </G>
        <G>
          <Rect x={252} y={184} width={5} height={28} fill="#C96E12" />
          <Path d="M254 154 L238 192 L271 192 Z" fill="#EC8A24" />
          <Path d="M254 166 L244 192 L266 192 Z" fill="#D97C1C" />
        </G>

        <Bike x={96} y={190} />
        <Bike x={146} y={197} scale={0.92} muted />
      </G>
    </Svg>
  );
}

function Bike({ x, y, scale = 1, muted = false }: { x: number; y: number; scale?: number; muted?: boolean }) {
  const strong = muted ? '#767676' : '#1C1C1C';
  const spoke = muted ? '#9A9A9A' : '#3A3A3A';
  const body = muted ? '#808080' : '#262626';
  return (
    <G transform={`translate(${x} ${y}) scale(${scale})`}>
      {[9, 35].map((cx) => (
        <G key={cx}>
          <Circle cx={cx} cy={24} r={8.5} fill="none" stroke={strong} strokeWidth={2.6} />
          <Line x1={cx} y1={15.5} x2={cx} y2={32.5} stroke={spoke} strokeWidth={1.3} />
          <Line x1={cx - 8.5} y1={24} x2={cx + 8.5} y2={24} stroke={spoke} strokeWidth={1.3} />
        </G>
      ))}
      <Path d="M9 24 L22 24 L16 10 M22 24 L28 10 M16 10 L28 10 M28 10 L35 24" fill="none" stroke={strong} strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round" />
      <Ellipse cx={15} cy={9} rx={4} ry={1.4} fill={muted ? '#6B6B6B' : '#111111'} />
      <Rect x={28} y={7} width={7} height={5} rx={1} fill="none" stroke={spoke} strokeWidth={1.6} />
      <Path d="M19 9 L24 -2" stroke={body} strokeWidth={4.2} strokeLinecap="round" />
      <Path d="M23 1 L31 9" stroke={body} strokeWidth={3} strokeLinecap="round" />
      <Path d="M20 8 L22 24" stroke={muted ? '#6B6B6B' : '#111111'} strokeWidth={3} strokeLinecap="round" />
      <Path d="M20 -3 A4.2 4.2 0 0 1 29 -3 L27 1 L22 1 Z" fill={strong} />
      <Circle cx={24.5} cy={-4.5} r={3.8} fill={muted ? '#A5A5A5' : '#4A4A4A'} />
    </G>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  brand: {
    marginTop: -66,
    color: '#FFFFFF',
    fontSize: 42,
    fontWeight: '800',
    letterSpacing: -1.25,
    lineHeight: 48,
    textShadowColor: 'rgba(150,60,0,.28)',
    textShadowOffset: { width: 0, height: 3 },
    textShadowRadius: 14,
  },
  illustration: {
    marginTop: 62,
  },
});
