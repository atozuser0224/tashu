import { Ionicons } from '@expo/vector-icons';
import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

export type AppSection = 'mission' | 'rewards' | 'settings';

type Props = {
  visible: boolean;
  active: AppSection;
  driverId: string;
  onSelect: (section: AppSection) => void;
  onClose: () => void;
  onLogout: () => void;
};

const ACCENT = '#1FA35C';
const ACCENT_SOFT = '#D5EBDD';
const INK = '#201E1D';

const visibleItems: Array<{
  key: AppSection;
  label: string;
  icon: keyof typeof Ionicons.glyphMap;
}> = [
  { key: 'mission', label: '메인 지도', icon: 'location-outline' },
  { key: 'rewards', label: '리워드 확인', icon: 'cash-outline' },
  { key: 'settings', label: '환경설정', icon: 'settings-outline' },
];

export function AppDrawer({
  visible,
  active,
  driverId: _driverId,
  onSelect,
  onClose,
  onLogout: _onLogout,
}: Props) {
  const content = (
      <View style={styles.overlay}>
        <Pressable
          accessibilityLabel="메뉴 닫기"
          style={StyleSheet.absoluteFill}
          onPress={onClose}
        />

        <View style={styles.drawer}>
          <View style={styles.brand}>
            <View style={styles.logo}>
              <Ionicons name="bicycle-outline" size={28} color="#FFFFFF" />
            </View>
            <View style={styles.brandCopy}>
              <Text style={styles.brandName}>타슈캐스트</Text>
              <Text style={styles.brandCaption}>자전거 재배치 파트너</Text>
            </View>
          </View>

          <View style={styles.menu}>
            {visibleItems.map((item) => {
              const selected = item.key === active;
              return (
                <Pressable
                  key={item.key}
                  accessibilityRole="button"
                  accessibilityState={{ selected }}
                  onPress={() => onSelect(item.key)}
                  style={({ pressed }) => [
                    styles.menuItem,
                    selected && styles.menuItemActive,
                    pressed && styles.menuItemPressed,
                  ]}
                >
                  <Ionicons
                    name={item.icon}
                    size={22}
                    color={selected ? ACCENT : INK}
                  />
                  <Text style={[styles.menuLabel, selected && styles.menuLabelActive]}>
                    {item.label}
                  </Text>
                </Pressable>
              );
            })}
          </View>

          <View style={styles.curveSlot} pointerEvents="none">
            <View style={styles.curve} />
          </View>
        </View>
      </View>
  );

  if (Platform.OS === 'web') {
    return visible ? <View style={styles.webModal}>{content}</View> : null;
  }

  return (
    <Modal
      visible={visible}
      transparent
      animationType="fade"
      statusBarTranslucent
      onRequestClose={onClose}
    >
      {content}
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    backgroundColor: 'rgba(70,66,60,0.4)',
  },
  webModal: {
    position: 'absolute',
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 100,
  },
  drawer: {
    width: '80%',
    maxWidth: 300,
    height: '100%',
    overflow: 'hidden',
    paddingTop: 60,
    paddingHorizontal: 20,
    backgroundColor: '#EDEDED',
    shadowColor: '#000000',
    shadowOffset: { width: 10, height: 0 },
    shadowOpacity: 0.25,
    shadowRadius: 40,
    elevation: 18,
  },
  brand: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 4,
  },
  logo: {
    width: 54,
    height: 54,
    flexShrink: 0,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 27,
    backgroundColor: ACCENT,
  },
  brandCopy: {
    flex: 1,
    marginLeft: 14,
  },
  brandName: {
    color: INK,
    fontSize: 20,
    fontWeight: '800',
    letterSpacing: -0.4,
  },
  brandCaption: {
    marginTop: 2,
    color: '#7D7979',
    fontSize: 12,
    fontWeight: '400',
  },
  menu: {
    marginTop: 34,
    gap: 6,
  },
  menuItem: {
    width: '100%',
    minHeight: 52,
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 15,
    paddingHorizontal: 16,
    borderRadius: 14,
  },
  menuItemActive: {
    backgroundColor: ACCENT_SOFT,
  },
  menuItemPressed: {
    opacity: 0.66,
  },
  menuLabel: {
    marginLeft: 14,
    color: INK,
    fontSize: 16,
    fontWeight: '700',
  },
  menuLabelActive: {
    color: ACCENT,
  },
  curveSlot: {
    height: 110,
    marginTop: 'auto',
    position: 'relative',
  },
  curve: {
    position: 'absolute',
    left: -40,
    right: -40,
    bottom: -50,
    height: 150,
    borderTopLeftRadius: 180,
    borderTopRightRadius: 180,
    backgroundColor: ACCENT,
  },
});
