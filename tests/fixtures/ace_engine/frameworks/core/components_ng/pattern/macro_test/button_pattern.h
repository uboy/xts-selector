#ifndef FOUNDATION_ACE_FRAMEWORKS_CORE_COMPONENTS_NG_PATTERN_MACRO_TEST_BUTTON_PATTERN_H
#define FOUNDATION_ACE_FRAMEWORKS_CORE_COMPONENTS_NG_PATTERN_MACRO_TEST_BUTTON_PATTERN_H

#include "base/memory/referenced.h"
#include "core/components_ng/pattern/pattern.h"

namespace OHOS::Ace::NG {
class ButtonPattern : public Pattern {
    DECLARE_ACE_TYPE(ButtonPattern, Pattern);
public:
    void OnModifyDone() override;
    // ACE_DEFINE_PROPERTY macro should generate SetRole method
};

ACE_DEFINE_PROPERTY(ButtonPattern, role)
}
}
#endif
