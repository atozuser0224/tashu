import { Ionicons } from '@expo/vector-icons';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { colors, fonts } from '../theme';

type Props = {
  title: string;
  subtitle?: string;
  onMenu: () => void;
  action?: { icon: keyof typeof Ionicons.glyphMap; onPress: () => void; label: string };
};

export function ScreenHeader({ title, subtitle, onMenu, action }: Props) {
  return (
    <View style={styles.root}>
      <Pressable accessibilityLabel="메뉴 열기" onPress={onMenu} style={styles.iconButton}>
        <Ionicons name="menu" size={25} color={colors.ink} />
      </Pressable>
      <View style={styles.titles}>
        <Text style={styles.title}>{title}</Text>
        {subtitle ? <Text style={styles.subtitle} numberOfLines={1}>{subtitle}</Text> : null}
      </View>
      {action ? (
        <Pressable accessibilityLabel={action.label} onPress={action.onPress} style={styles.iconButton}>
          <Ionicons name={action.icon} size={22} color={colors.ink} />
        </Pressable>
      ) : <View style={styles.iconButton} />}
    </View>
  );
}

const styles = StyleSheet.create({
  root: { minHeight: 64, paddingHorizontal: 16, flexDirection: 'row', alignItems: 'center', backgroundColor: colors.paper, borderBottomWidth: 1, borderBottomColor: colors.line },
  iconButton: { width: 42, height: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 14 },
  titles: { flex: 1, alignItems: 'center', paddingHorizontal: 8 },
  title: { color: colors.ink, fontFamily: fonts.extraBold, fontSize: 17 },
  subtitle: { maxWidth: 220, marginTop: 2, color: colors.muted, fontFamily: fonts.semibold, fontSize: 10 },
});
