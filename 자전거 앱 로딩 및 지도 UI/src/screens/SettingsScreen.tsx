import { Ionicons } from '@expo/vector-icons';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import type { DriverProfile } from './ProfileSetupScreen';
import { fonts } from '../theme';

type SettingsProfile = DriverProfile & { email?: string };

type Props = {
  onMenu: () => void;
  profile: SettingsProfile | null;
  onLogout: () => void;
};

type NotificationKey = 'push' | 'location' | 'recommendation';

const ACCENT = '#1FA35C';
const INK = '#201E1D';
const MUTED = '#9B9797';
const CANVAS = '#F3F2F2';
const DANGER = '#D0442A';

export function SettingsScreen({ onMenu, profile, onLogout }: Props) {
  const [notifications, setNotifications] = useState<Record<NotificationKey, boolean>>({
    push: true,
    location: true,
    recommendation: false,
  });

  const toggleNotification = (key: NotificationKey) => {
    setNotifications((current) => ({ ...current, [key]: !current[key] }));
  };

  return (
    <View style={styles.root}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="메뉴 열기"
        onPress={onMenu}
        style={({ pressed }) => [styles.menuButton, pressed && styles.pressed]}
      >
        <Ionicons name="menu" size={22} color={INK} />
      </Pressable>

      <ScrollView
        contentContainerStyle={styles.content}
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.titleRow}>
          <View style={styles.titleAccent} />
          <Text style={styles.title}>환경설정</Text>
        </View>

        <SectionLabel>내 정보</SectionLabel>
        <View style={styles.profileCard}>
          <ProfileRow label="이름" value={profile?.name || '-'} />
          <ProfileRow label="생년월일" value={profile?.birthDate || profile?.birthYear || '-'} />
          <ProfileRow label="성별" value={profile?.gender || '-'} />
          <ProfileRow label="전화번호" value={profile?.phone || '-'} />
          <ProfileRow label="이메일" value={profile?.email || 'rider@gmail.com'} last />
        </View>

        <SectionLabel>알림 설정</SectionLabel>
        <View style={styles.listCard}>
          <NotificationRow
            label="푸시 알림"
            enabled={notifications.push}
            onToggle={() => toggleNotification('push')}
          />
          <NotificationRow
            label="위치 서비스"
            enabled={notifications.location}
            onToggle={() => toggleNotification('location')}
          />
          <NotificationRow
            label="재배치 추천 알림"
            enabled={notifications.recommendation}
            onToggle={() => toggleNotification('recommendation')}
            last
          />
        </View>

        <SectionLabel>기타</SectionLabel>
        <View style={styles.listCard}>
          <MenuRow label="정보 수정하기" />
          <MenuRow label="문의사항" />
          <MenuRow label="로그아웃" onPress={onLogout} />
          <MenuRow label="탈퇴하기" danger last />
        </View>
      </ScrollView>
    </View>
  );
}

function SectionLabel({ children }: { children: string }) {
  return <Text style={styles.sectionLabel}>{children}</Text>;
}

function ProfileRow({
  label,
  value,
  last = false,
}: {
  label: string;
  value: string;
  last?: boolean;
}) {
  return (
    <View style={[styles.profileRow, !last && styles.rowBorder]}>
      <Text style={styles.profileLabel}>{label}</Text>
      <Text style={styles.profileValue} numberOfLines={1}>{value}</Text>
    </View>
  );
}

function NotificationRow({
  label,
  enabled,
  onToggle,
  last = false,
}: {
  label: string;
  enabled: boolean;
  onToggle: () => void;
  last?: boolean;
}) {
  return (
    <Pressable
      accessibilityRole="switch"
      accessibilityState={{ checked: enabled }}
      accessibilityLabel={label}
      onPress={onToggle}
      style={({ pressed }) => [
        styles.notificationRow,
        !last && styles.rowBorder,
        pressed && styles.rowPressed,
      ]}
    >
      <Text style={styles.notificationLabel}>{label}</Text>
      <View style={[styles.switchTrack, enabled ? styles.switchTrackOn : styles.switchTrackOff]}>
        <View style={[styles.switchThumb, enabled ? styles.switchThumbOn : styles.switchThumbOff]} />
      </View>
    </Pressable>
  );
}

function MenuRow({
  label,
  danger = false,
  last = false,
  onPress,
}: {
  label: string;
  danger?: boolean;
  last?: boolean;
  onPress?: () => void;
}) {
  return (
    <Pressable
      accessibilityRole="button"
      disabled={!onPress}
      onPress={onPress}
      style={({ pressed }) => [
        styles.menuRow,
        !last && styles.rowBorder,
        pressed && styles.rowPressed,
      ]}
    >
      <Text style={[styles.menuLabel, danger && styles.menuLabelDanger]}>{label}</Text>
      <Ionicons
        name="chevron-forward"
        size={18}
        color={danger ? '#E6B4AB' : '#C3BFBC'}
      />
    </Pressable>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    backgroundColor: CANVAS,
  },
  menuButton: {
    position: 'absolute',
    top: 58,
    left: 22,
    zIndex: 40,
    width: 46,
    height: 46,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 14,
    backgroundColor: '#FFFFFF',
    shadowColor: '#000000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.14,
    shadowRadius: 16,
    elevation: 7,
  },
  pressed: {
    opacity: 0.68,
  },
  content: {
    paddingTop: 120,
    paddingHorizontal: 24,
    paddingBottom: 40,
  },
  titleRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  titleAccent: {
    width: 6,
    height: 24,
    borderRadius: 3,
    backgroundColor: ACCENT,
  },
  title: {
    marginLeft: 10,
    color: INK,
    fontFamily: fonts.extraBold,
    fontSize: 26,
    letterSpacing: -0.78,
  },
  sectionLabel: {
    marginTop: 24,
    color: INK,
    fontFamily: fonts.extraBold,
    fontSize: 15,
  },
  profileCard: {
    marginTop: 10,
    paddingVertical: 6,
    paddingHorizontal: 18,
    borderRadius: 18,
    backgroundColor: '#FFFFFF',
  },
  listCard: {
    marginTop: 10,
    overflow: 'hidden',
    borderRadius: 18,
    backgroundColor: '#FFFFFF',
  },
  rowBorder: {
    borderBottomWidth: 1,
    borderBottomColor: '#F0EEEB',
  },
  rowPressed: {
    backgroundColor: '#FAF8F6',
  },
  profileRow: {
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 13,
  },
  profileLabel: {
    width: 74,
    flexShrink: 0,
    color: MUTED,
    fontFamily: fonts.semibold,
    fontSize: 13,
  },
  profileValue: {
    flex: 1,
    marginLeft: 14,
    color: INK,
    fontFamily: fonts.semibold,
    fontSize: 14.5,
  },
  notificationRow: {
    minHeight: 59,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
  },
  notificationLabel: {
    color: INK,
    fontFamily: fonts.semibold,
    fontSize: 15,
  },
  switchTrack: {
    width: 46,
    height: 27,
    position: 'relative',
    borderRadius: 14,
  },
  switchTrackOn: {
    backgroundColor: ACCENT,
  },
  switchTrackOff: {
    backgroundColor: '#D7D3D3',
  },
  switchThumb: {
    position: 'absolute',
    top: 3,
    width: 21,
    height: 21,
    borderRadius: 10.5,
    backgroundColor: '#FFFFFF',
  },
  switchThumbOn: {
    right: 3,
  },
  switchThumbOff: {
    left: 3,
  },
  menuRow: {
    minHeight: 55,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: 16,
  },
  menuLabel: {
    color: INK,
    fontFamily: fonts.semibold,
    fontSize: 15,
  },
  menuLabelDanger: {
    color: DANGER,
  },
});
