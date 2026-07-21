import { useEffect, useRef, useState } from 'react';
import { CameraView, type BarcodeScanningResult, useCameraPermissions } from 'expo-camera';
import { Ionicons } from '@expo/vector-icons';
import {
  Animated,
  Easing,
  Modal,
  Platform,
  Pressable,
  SafeAreaView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

type Props = {
  visible: boolean;
  title: string;
  description: string;
  expectedCount?: number;
  onComplete: (codes: string[]) => void;
  onClose: () => void;
};

export function QrScannerModal({
  visible,
  title,
  description,
  expectedCount = 1,
  onComplete,
  onClose,
}: Props) {
  const [permission, requestPermission] = useCameraPermissions();
  const [codes, setCodes] = useState<string[]>([]);
  const [paused, setPaused] = useState(false);
  const codesRef = useRef<string[]>([]);
  const scanLockedRef = useRef(false);
  const completionLockedRef = useRef(false);
  const visibleRef = useRef(visible);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const scanLine = useRef(new Animated.Value(0)).current;

  const clearTimer = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };

  useEffect(() => {
    visibleRef.current = visible;
    clearTimer();
    if (visible) {
      codesRef.current = [];
      scanLockedRef.current = false;
      completionLockedRef.current = false;
      setCodes([]);
      setPaused(false);
    } else {
      completionLockedRef.current = true;
    }
    return clearTimer;
  }, [visible]);

  useEffect(() => () => clearTimer(), []);

  useEffect(() => {
    scanLine.stopAnimation();
    scanLine.setValue(0);
    if (!visible || paused) return undefined;
    const animation = Animated.loop(
      Animated.sequence([
        Animated.timing(scanLine, {
          toValue: 1,
          duration: 1550,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
        Animated.timing(scanLine, {
          toValue: 0,
          duration: 1550,
          easing: Easing.inOut(Easing.ease),
          useNativeDriver: true,
        }),
      ]),
    );
    animation.start();
    return () => animation.stop();
  }, [paused, scanLine, visible]);

  const scheduleComplete = (next: string[]) => {
    if (completionLockedRef.current) return;
    completionLockedRef.current = true;
    scanLockedRef.current = true;
    setPaused(true);
    clearTimer();
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      if (visibleRef.current) onComplete(next);
    }, 850);
  };

  const capture = (value: string) => {
    const trimmed = value.trim();
    if (!trimmed || scanLockedRef.current || completionLockedRef.current || codesRef.current.includes(trimmed)) return;
    scanLockedRef.current = true;
    const next = [...codesRef.current, trimmed].slice(0, expectedCount);
    codesRef.current = next;
    setCodes(next);
    setPaused(true);
    if (next.length >= expectedCount) {
      scanLockedRef.current = false;
      scheduleComplete(next);
    } else {
      clearTimer();
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        if (!visibleRef.current) return;
        scanLockedRef.current = false;
        setPaused(false);
      }, 650);
    }
  };

  const handleBarcode = ({ data }: BarcodeScanningResult) => capture(data);

  const close = () => {
    visibleRef.current = false;
    completionLockedRef.current = true;
    scanLockedRef.current = true;
    clearTimer();
    onClose();
  };

  const requiredCount = Math.max(1, expectedCount);
  const completed = codes.length >= requiredCount;
  const accent = title.includes('회수') || title.includes('적재') ? '#1FA35C' : '#F7941D';
  const scanLineTranslate = scanLine.interpolate({ inputRange: [0, 1], outputRange: [0, 212] });

  const content = (
      <SafeAreaView style={styles.root}>
        <View style={styles.header}>
          <View style={styles.headerCopy}>
            <Text style={styles.title}>{title}</Text>
            <Text style={styles.description}>{description}</Text>
          </View>
          <Pressable accessibilityLabel="QR 스캔 닫기" onPress={close} style={styles.closeButton}>
            <Ionicons name="close" size={20} color="#FFFFFF" />
          </Pressable>
        </View>

        <View style={styles.content}>
          {completed ? (
            <View style={styles.completeWrap}>
              <View style={[styles.completeCircle, { backgroundColor: accent }]}>
                <Ionicons name="checkmark" size={54} color="#FFFFFF" />
              </View>
              <Text style={styles.completeTitle}>QR 확인 완료</Text>
              <Text style={styles.completeCount}>{codes.length}개 스캔을 서버에 반영하는 중입니다</Text>
            </View>
          ) : (
            <>
              <View style={styles.cameraFrame}>
                {permission?.granted ? (
                  <CameraView
                    style={StyleSheet.absoluteFill}
                    facing="back"
                    barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
                    onBarcodeScanned={paused ? undefined : handleBarcode}
                  />
                ) : (
                  <View style={styles.permission}>
                    <Ionicons name="camera-outline" size={42} color="#FFFFFF" />
                    <Text style={styles.permissionText}>실제 QR 스캔에는 카메라 권한이 필요합니다.</Text>
                    <Pressable onPress={requestPermission} style={styles.permissionButton}>
                      <Text style={styles.permissionButtonText}>카메라 권한 허용</Text>
                    </Pressable>
                  </View>
                )}

                <View pointerEvents="none" style={StyleSheet.absoluteFill}>
                  <View style={[styles.corner, styles.cornerTopLeft, { borderColor: accent }]} />
                  <View style={[styles.corner, styles.cornerTopRight, { borderColor: accent }]} />
                  <View style={[styles.corner, styles.cornerBottomLeft, { borderColor: accent }]} />
                  <View style={[styles.corner, styles.cornerBottomRight, { borderColor: accent }]} />
                  <Animated.View
                    style={[
                      styles.scanLine,
                      {
                        backgroundColor: accent,
                        shadowColor: accent,
                        transform: [{ translateY: scanLineTranslate }],
                      },
                    ]}
                  />
                </View>
              </View>

              <View style={styles.progressPill}>
                <View style={[styles.progressDot, { backgroundColor: accent }]} />
                <Text style={styles.progressText}>{codes.length} / {requiredCount}</Text>
              </View>
            </>
          )}
        </View>

        <View style={styles.footerSpacer} />
      </SafeAreaView>
  );

  if (Platform.OS === 'web') {
    return visible ? <View style={styles.webModal}>{content}</View> : null;
  }

  return (
    <Modal visible={visible} animationType="fade" onRequestClose={close} statusBarTranslucent>
      {content}
    </Modal>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#15130F' },
  webModal: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, zIndex: 120 },
  header: {
    flexDirection: 'row', alignItems: 'flex-start', gap: 14,
    paddingHorizontal: 26, paddingTop: Platform.OS === 'web' ? 58 : 22,
  },
  headerCopy: { flex: 1 },
  title: { color: '#FFFFFF', fontSize: 26, lineHeight: 30, fontWeight: '800', letterSpacing: -0.8 },
  description: { marginTop: 7, color: 'rgba(255,255,255,.6)', fontSize: 13, lineHeight: 19, fontWeight: '500' },
  closeButton: {
    width: 38, height: 38, borderRadius: 19, alignItems: 'center', justifyContent: 'center',
    backgroundColor: 'rgba(255,255,255,.12)',
  },
  content: { flex: 1, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 30 },
  cameraFrame: {
    width: 248, height: 248, overflow: 'hidden', borderRadius: 24,
    backgroundColor: 'rgba(255,255,255,.06)',
  },
  permission: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 22, backgroundColor: '#211E19' },
  permissionText: { marginTop: 12, color: 'rgba(255,255,255,.68)', fontSize: 12, lineHeight: 18, textAlign: 'center' },
  permissionButton: { marginTop: 14, paddingHorizontal: 14, paddingVertical: 9, borderRadius: 10, backgroundColor: '#FFFFFF' },
  permissionButtonText: { color: '#201E1D', fontSize: 11, fontWeight: '800' },
  corner: { position: 'absolute', width: 38, height: 38 },
  cornerTopLeft: { left: 12, top: 12, borderLeftWidth: 5, borderTopWidth: 5, borderTopLeftRadius: 14 },
  cornerTopRight: { right: 12, top: 12, borderRightWidth: 5, borderTopWidth: 5, borderTopRightRadius: 14 },
  cornerBottomLeft: { left: 12, bottom: 12, borderLeftWidth: 5, borderBottomWidth: 5, borderBottomLeftRadius: 14 },
  cornerBottomRight: { right: 12, bottom: 12, borderRightWidth: 5, borderBottomWidth: 5, borderBottomRightRadius: 14 },
  scanLine: {
    position: 'absolute', left: 10, right: 10, top: 12, height: 3, borderRadius: 2,
    shadowOpacity: 1, shadowRadius: 10, shadowOffset: { width: 0, height: 0 }, elevation: 8,
  },
  progressPill: {
    marginTop: 24, flexDirection: 'row', alignItems: 'center', gap: 8,
    paddingHorizontal: 16, paddingVertical: 8, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,.1)',
  },
  progressDot: { width: 8, height: 8, borderRadius: 4 },
  progressText: { color: '#FFFFFF', fontSize: 14, fontWeight: '800' },
  completeWrap: { alignItems: 'center' },
  completeCircle: {
    width: 104, height: 104, borderRadius: 52, alignItems: 'center', justifyContent: 'center',
    shadowColor: '#000000', shadowOpacity: .45, shadowRadius: 17, shadowOffset: { width: 0, height: 14 }, elevation: 12,
  },
  completeTitle: { marginTop: 20, color: '#FFFFFF', fontSize: 21, fontWeight: '800', letterSpacing: -0.5 },
  completeCount: { marginTop: 7, color: 'rgba(255,255,255,.58)', fontSize: 12, fontWeight: '600' },
  footerSpacer: { height: 118 },
});
