import { useEffect, useRef } from 'react';
import { StatusBar } from 'expo-status-bar';
import { LinearGradient } from 'expo-linear-gradient';
import { Animated, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Circle, Ellipse, G, Path } from 'react-native-svg';

const BRAND = '타슈캐스트';

export function LoginScreen({ onLogin }: { onLogin: () => void }) {
  const bounce = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(bounce, { toValue: 1, duration: 430, useNativeDriver: true }),
        Animated.timing(bounce, { toValue: 0, duration: 720, useNativeDriver: true }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [bounce]);

  return (
    <View style={styles.root}>
      <StatusBar style="dark" />
      <LinearGradient
        colors={['#FCA632', '#F7941D', '#EC7C15', '#25A35E']}
        locations={[0, 0.55, 0.74, 1]}
        style={StyleSheet.absoluteFill}
      />

      <View style={styles.hero}>
        <Animated.View
          style={{
            transform: [
              { translateY: bounce.interpolate({ inputRange: [0, 1], outputRange: [0, -14] }) },
              { rotate: bounce.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '-1.5deg'] }) },
            ],
          }}
        >
          <CloudRiderMascot />
        </Animated.View>
        <View style={styles.brandBlock}>
          <Text style={styles.brand}>{BRAND}</Text>
          <Text style={styles.subtitle}>자전거 재배치 파트너 서비스</Text>
        </View>
      </View>

      <View style={styles.loginArea}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Google 계정으로 로그인"
          onPress={onLogin}
          style={({ pressed }) => [styles.googleButton, pressed && styles.googleButtonPressed]}
        >
          <GoogleMark />
          <Text style={styles.googleLabel}>Google 계정으로 로그인</Text>
        </Pressable>
      </View>
    </View>
  );
}

function CloudRiderMascot() {
  return (
    <Svg width={170} height={165} viewBox="0 0 170 165">
      <Path d="M22 54 q7 -8 14 0 q7 8 14 0" stroke="#FFFFFF" strokeWidth={3} fill="none" strokeLinecap="round" />
      <Path d="M138 40 L138 58 M129 49 L147 49" stroke="#FFFFFF" strokeWidth={3} strokeLinecap="round" />
      <G fill="#FFFFFF">
        <Circle cx={68} cy={72} r={25} />
        <Circle cx={100} cy={68} r={23} />
        <Circle cx={116} cy={86} r={21} />
        <Circle cx={56} cy={90} r={21} />
        <Circle cx={85} cy={93} r={27} />
        <Circle cx={108} cy={101} r={18} />
      </G>
      <Path d="M46 92 q-11 2 -15 13 M124 92 q11 2 15 13" stroke="#FFFFFF" strokeWidth={4.5} fill="none" strokeLinecap="round" />
      <Ellipse cx={76} cy={84} rx={5.2} ry={7} fill="#2A1C08" />
      <Ellipse cx={98} cy={84} rx={5.2} ry={7} fill="#2A1C08" />
      <Circle cx={78} cy={81} r={1.6} fill="#FFFFFF" />
      <Circle cx={100} cy={81} r={1.6} fill="#FFFFFF" />
      <Path d="M82 96 q5 5 11 0" stroke="#2A1C08" strokeWidth={2.6} fill="none" strokeLinecap="round" />
      <Path d="M76 116 L82 126 M96 116 L90 126" stroke="#FFFFFF" strokeWidth={4.5} strokeLinecap="round" />
      <Circle cx={86} cy={138} r={18} fill="none" stroke="#FFFFFF" strokeWidth={3.5} />
      <Circle cx={86} cy={138} r={2.6} fill="#FFFFFF" />
      <Path d="M86 138 L86 121 M86 138 L102 131 M86 138 L99 151 M86 138 L73 151 M86 138 L70 131" stroke="#FFFFFF" strokeWidth={1.7} />
    </Svg>
  );
}

function GoogleMark() {
  return (
    <Svg width={20} height={20} viewBox="0 0 48 48">
      <Path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <Path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <Path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.28-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24s.92 7.54 2.56 10.78l7.97-6.19z" />
      <Path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </Svg>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
  },
  hero: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingBottom: 20,
  },
  brandBlock: {
    alignItems: 'center',
    marginTop: 16,
  },
  brand: {
    color: '#FFFFFF',
    fontSize: 40,
    fontWeight: '800',
    letterSpacing: -1.2,
    lineHeight: 46,
    textShadowColor: 'rgba(150,60,0,.28)',
    textShadowOffset: { width: 0, height: 3 },
    textShadowRadius: 14,
  },
  subtitle: {
    marginTop: 7,
    color: '#FFFFFF',
    fontSize: 13,
    fontWeight: '600',
    letterSpacing: -0.1,
    opacity: 0.88,
  },
  loginArea: {
    marginHorizontal: 24,
    marginBottom: 54,
  },
  googleButton: {
    minHeight: 54,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 11,
    paddingHorizontal: 16,
    paddingVertical: 15,
    borderWidth: 1.5,
    borderColor: '#E2E0DD',
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
  },
  googleButtonPressed: {
    backgroundColor: '#F7F6F5',
  },
  googleLabel: {
    color: '#201E1D',
    fontSize: 15,
    fontWeight: '700',
  },
});
