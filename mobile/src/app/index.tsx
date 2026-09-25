import { Text, View } from 'react-native';

import { APP_NAME } from '@/config';

export default function Index() {
  return (
    <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
      <Text>{APP_NAME}</Text>
    </View>
  );
}
