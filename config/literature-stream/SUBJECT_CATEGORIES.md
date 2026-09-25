# 文献分类体系（8大学科类 × 4大文献类型）



## 概述
本文档定义文献流模块的**二维分类体系**，基于PubMed的MeSH主题词构建。

### 分类维度
- **维度1**: 学科子类（8大类）
- **维度2**: 文献类型（4大类，其中原创研究展开3个子类）

---
用户需要先选择学科子类（可多选），再选择文献类型（或可不选）；选文献类型时直接在整层检索式后套文献类型检索式。
如果用户不选择学科子类直接选文献类型，则按下述通用闸门套文献类型检索式：
(
  "Sports"[mh] OR
  "Athletes"[mh] OR
  "Athletic Performance"[mh] OR
  "Sports Medicine"[mh] OR
  "Athletic Injuries"[mh] OR
  "Physical Education and Training"[mh] OR
  "Athletic Equipment"[mh] OR
  "Olympic Games"[mh] OR
  sport*[tiab] OR
  athlet*[tiab] OR
  "physical education"[tiab] OR
  "phys ed"[tiab] OR
  "sport pedagogy"[tiab] OR
  "sports pedagogy"[tiab] OR
  Paralympic*[tiab] OR
  Olympic*[tiab] OR
  interscholastic[tiab] OR
  intercollegiate[tiab] OR
  (
    ("Equipment Design"[mh] OR
     "Protective Devices"[mh] OR
     "Wearable Electronic Devices"[mh] OR
     "Motion Capture"[mh] OR
     "Biomechanical Phenomena"[mh])
    AND
    (sport*[tiab] OR athlet*[tiab] OR "physical education"[tiab])
  )
)


## 📚 文献类型分类（维度2）

### 1. Meta分析 & 系统综述
**定义**: 对已发表研究进行系统性整合和定量/定性分析的文献。

**MeSH识别词**:
```
Meta-Analysis[pt]
Systematic Review[pt]
Review[pt] AND "systematic review"[ti]
```

**典型特征**:
- 有明确的系统检索策略
- 包含多项原始研究
- 通常有森林图、漏斗图等

---

### 2. 原创研究（展开3个子类）
**定义**: 报告新数据、新发现的一手研究。

#### 2.1 人体研究（Human Studies）
**MeSH识别词**:
```
Humans[mh]
Clinical Trial[pt]
Randomized Controlled Trial[pt]
Cohort Studies[mh]
Cross-Sectional Studies[mh]
Case-Control Studies[mh]
```

#### 2.2 动物研究（Animal Studies）
**MeSH识别词**:
```
Animals[mh] NOT Humans[mh]
Rats[mh]
Mice[mh]
Animal Experimentation[mh]
```

#### 2.3 N/A（理论/社科研究，无生物对象）
**定义**: 不涉及人体或动物实验的理论、社会科学、工程学研究。

**识别方式**:
```
NOT Humans[mh] AND NOT Animals[mh]
```


---

### 3. 综述（Review）
**定义**: 对某一主题的叙述性总结，非系统性综述。

**MeSH识别词**:
```
Review[pt] NOT (Meta-Analysis[pt] OR Systematic Review[pt])
```

**典型特征**:
- 无系统检索策略
- 专家观点综述
- 教科书式总结

---

### 4. 指南/共识/Protocol
**定义**: 临床实践指南、专家共识、研究方案等指导性文献。

**MeSH识别词**:
```
Practice Guideline[pt]
Guideline[pt]
Consensus Development Conference[pt]
"consensus statement"[ti]
"clinical practice guideline"[ti]
Protocol[ti]
```
指南（general）：Guideline[pt]

实践指南：Practice Guideline[pt]

共识会议：Consensus Development Conference[pt] OR Consensus Development Conference, NIH[pt]

共识主题（补充可选）：Consensus[mh] OR Consensus Development Conferences as Topic[mh]

研究方案/协议：

临床试验方案：Clinical Trial Protocol[pt]

更宽口径（很多期刊用标题标注）：protocol[ti] OR "study protocol"[ti]（可与上面合用）

---

## 🏃 学科子类分类（维度1）

## 1. 体育教育

### MeSH主题词
```

(
  Schools[mh] OR Students[mh] OR Faculty[mh] OR Curriculum[mh] OR Teaching[mh] OR
  Education, Primary[mh] OR Education, Secondary[mh] OR Education, Higher[mh] OR
  school*[tiab] OR student*[tiab] OR teacher*[tiab] OR classroom*[tiab] OR
  elementary education[tiab] OR primary education[tiab] OR
  secondary education[tiab] OR high school[tiab] OR college[tiab] OR university[tiab] OR
  school-based[tiab] OR school based[tiab] OR school-wide[tiab] OR school wide[tiab] OR
  whole-of-school[tiab] OR whole of school[tiab] OR whole school[tiab] OR
  interscholastic[tiab] OR intramural[tiab] OR after-school[tiab] OR afterschool[tiab] OR
  school sport*[tiab]
)
AND
(
  Motor Activity[mh] OR Movement[mh] OR Health Promotion[mh] OR
  Recreation[mh] OR Play and Playthings[mh] OR
  Physical Education and Training[mh] OR Exercise[mh] OR Physical Fitness[mh] OR
  Walking[mh] OR Bicycling[mh] OR Transportation[mh] OR Commuting[mh] OR
  School Health Services[mh] OR Health Policy[mh] OR Program Evaluation[mh] OR
  Sedentary Behavior[mh] OR Extracurricular Activities[mh] OR
  physical activity[tiab] OR physical activities[tiab] OR
  physical education[tiab] OR PE class[tiab] OR PE classes[tiab] OR PE lesson[tiab] OR PE lessons[tiab] OR
  gym class[tiab] OR gym lesson[tiab] OR gym lessons[tiab] OR
  phys ed[tiab] OR P.E.[tiab] OR
  physical literacy[tiab] OR health and physical education[tiab] OR physical and health education[tiab] OR
  sport pedagogy[tiab] OR sports pedagogy[tiab] OR sport didactic[tiab] OR sport didactics[tiab] OR
  physical education curriculum[tiab] OR
  physical education program[tiab] OR physical education programs[tiab] OR
  physical education programme[tiab] OR physical education programmes[tiab] OR
  physical education teacher[tiab] OR physical education teachers[tiab] OR PETE[tiab] OR
  physical education teacher education[tiab] OR
  Teaching Games for Understanding[tiab] OR TGfU[tiab] OR Sport Education[tiab] OR SEPEP[tiab] OR
  Teaching Personal and Social Responsibility[tiab] OR TPSR[tiab] OR cooperative learning[tiab] OR
  fundamental movement skill[tiab] OR fundamental movement skills[tiab] OR FMS[tiab] OR
  motor skill[tiab] OR motor skills[tiab] OR movement skill[tiab] OR movement skills[tiab] OR
  motor competence[tiab] OR movement competence[tiab] OR
  motor development[tiab] OR movement development[tiab] OR
  fitness education[tiab] OR fitness testing[tiab] OR FitnessGram[tiab] OR PACER[tiab] OR beep test[tiab] OR shuttle run[tiab] OR Cooper test[tiab] OR
  CSPAP[tiab] OR
  comprehensive school physical activity program[tiab] OR comprehensive school physical activity programs[tiab] OR
  comprehensive school physical activity programme[tiab] OR comprehensive school physical activity programmes[tiab] OR
  active school[tiab] OR active schools[tiab] OR
  active classroom[tiab] OR active classrooms[tiab] OR
  classroom physical activity[tiab] OR movement integration[tiab] OR
  activity break[tiab] OR activity breaks[tiab] OR brain break[tiab] OR brain breaks[tiab] OR
  recess[tiab] OR playground[tiab] OR playgrounds[tiab] OR playtime[tiab] OR lunchtime[tiab] OR
  after-school program[tiab] OR after-school programs[tiab] OR
  after school program[tiab] OR after school programs[tiab] OR afterschool[tiab] OR
  extracurricular activity[tiab] OR extracurricular activities[tiab] OR co-curricular[tiab] OR cocurricular[tiab] OR
  school wellness policy[tiab] OR physical activity policy[tiab] OR
  active travel to school[tiab] OR active commuting to school[tiab] OR
  walk to school[tiab] OR walking school bus[tiab] OR Safe Routes to School[tiab] OR
  bike to school[tiab] OR cycling to school[tiab] OR
  exergam*[tiab] OR active video game[tiab] OR active video games[tiab] OR
  school sport[tiab] OR school sports[tiab] OR
  interscholastic sport[tiab] OR interscholastic sports[tiab] OR interscholastic athletics[tiab] OR
  intramural sport[tiab] OR intramural sports[tiab] OR
  sedentary behavior[tiab] OR sedentary behaviour[tiab] OR physical inactivity[tiab] OR screen time[tiab]
)
NOT
(
  Pulmonary Embolism[mh] OR pulmonary embol*[tiab] OR
  protein electrophoresis[tiab] OR
  preeclampsia[tiab] OR pre-eclampsia[tiab] OR
  phosphatidylethanol[tiab]
)


```

### 典型期刊

---

## 2. 运动训练
**Training Science**

### MeSH主题词
```

(
  Sports[mh] OR Athletes[mh] OR Athletic Performance[mh] OR
  sport*[tiab] OR athlete*[tiab]
  OR
  (
    Animals[mh] AND
    (
      treadmill[tiab] OR treadmill run*[tiab] OR treadmill train*[tiab] OR
      wheel run*[tiab] OR wheel exercis*[tiab] OR voluntary wheel[tiab] OR voluntary running[tiab] OR forced running[tiab] OR
      swim training[tiab] OR swimming training[tiab] OR swim exercis*[tiab] OR
      ladder climb*[tiab] OR ladder-climb*[tiab] OR ladder resistance[tiab]
    )
  )
)
AND
(
  Physical Conditioning, Human[mh] OR Exercise[mh] OR Physical Fitness[mh] OR
  Resistance Training[mh] OR Endurance Training[mh] OR High-Intensity Interval Training[mh] OR
  Circuit-Based Exercise[mh] OR Plyometric Exercise[mh] OR Muscle Stretching Exercises[mh] OR
  Blood Flow Restriction Therapy[mh] OR
  periodization[tiab] OR periodisation[tiab] OR progressive overload[tiab] OR overload[tiab] OR
  specificity[tiab] OR taper[tiab] OR tapers[tiab] OR peaking[tiab] OR deload[tiab] OR detraining[tiab] OR
  overreaching[tiab] OR overtraining[tiab] OR
  resistance training[tiab] OR strength training[tiab] OR weight training[tiab] OR
  weightlifting[tiab] OR powerlifting[tiab] OR eccentric training[tiab] OR isometric training[tiab] OR
  isokinetic training[tiab] OR flywheel training[tiab] OR velocity-based training[tiab] OR VBT[tiab] OR
  endurance training[tiab] OR aerobic training[tiab] OR interval training[tiab] OR
  high-intensity interval training[tiab] OR HIIT[tiab] OR sprint interval training[tiab] OR SIT[tiab] OR
  repeated sprint[tiab] OR speed training[tiab] OR
  small-sided game[tiab] OR small-sided games[tiab] OR small sided game[tiab] OR small sided games[tiab] OR SSG[tiab] OR
  agility training[tiab] OR change of direction[tiab] OR COD[tiab] OR
  power training[tiab] OR muscle power[tiab] OR rate of force development[tiab] OR RFD[tiab] OR
  one-repetition maximum[tiab] OR one repetition maximum[tiab] OR 1RM[tiab] OR
  balance training[tiab] OR flexibility training[tiab] OR
  concurrent training[tiab] OR complex training[tiab] OR contrast training[tiab] OR
  cluster set[tiab] OR cluster sets[tiab] OR rest-pause[tiab] OR rest pause[tiab] OR time under tension[tiab] OR TUT[tiab] OR
  warm-up[tiab] OR warm up[tiab] OR cool-down[tiab] OR cool down[tiab] OR
  altitude training[tiab] OR hypoxic training[tiab] OR intermittent hypoxic training[tiab] OR
  live high train low[tiab] OR LHTL[tiab] OR live low train high[tiab] OR LLTH[tiab] OR
  heat acclimation[tiab] OR heat acclimatization[tiab] OR cold-water immersion[tiab] OR cold water immersion[tiab] OR cryotherapy[tiab] OR
  blood flow restriction[tiab] OR occlusion training[tiab] OR kaatsu[tiab] OR
  training load[tiab] OR workload[tiab] OR internal load[tiab] OR external load[tiab] OR
  session RPE[tiab] OR sRPE[tiab] OR HRV[tiab] OR heart rate variability[tiab] OR TRIMP[tiab] OR
  GPS[tiab] OR acceleromet*[tiab] OR ACWR[tiab] OR acute:chronic workload ratio[tiab] OR
  skill acquisition[tiab] OR practice design[tiab] OR constraints-led[tiab] OR constraints led[tiab] OR differential learning[tiab]
)



```

### 典型期刊


---

## 3. 体质健康与监测
**Physical Fitness, Health and Monitoring**


### MeSH主题词
```
(
  Physical Fitness[mh] OR Exercise[mh] OR Motor Activity[mh] OR Exercise Test[mh] OR
  Physical Endurance[mh] OR Muscle Strength[mh] OR Body Composition[mh] OR Anthropometry[mh] OR
  Sedentary Behavior[mh] OR Health Promotion[mh] OR Health Education[mh] OR
  "physical fitness"[tiab] OR "cardiorespiratory fitness"[tiab] OR "functional capacity"[tiab] OR
  "physical activ*"[tiab] OR exercis*[tiab] OR "exercise training"[tiab]
)
AND
(
  Monitoring, Physiologic[mh] OR Wearable Electronic Devices[mh] OR Accelerometry[mh] OR Actigraphy[mh] OR
  Electrocardiography[mh] OR Heart Rate[mh] OR Oxygen Saturation[mh] OR Photoplethysmography[mh] OR
  Blood Pressure Monitoring, Ambulatory[mh] OR Oxygen Consumption[mh] OR Calorimetry, Indirect[mh] OR
  acceleromet*[tiab] OR actigraph*[tiab] OR pedometer*[tiab] OR "activity monitor*"[tiab] OR
  "fitness tracker*"[tiab] OR smartwatch[tiab] OR "smart watch"[tiab] OR IMU[tiab] OR
  "inertial measurement unit"[tiab] OR gyroscope[tiab] OR magnetometer[tiab] OR GPS[tiab] OR
  "global positioning system"[tiab] OR "heart rate"[tiab] OR HRV[tiab] OR
  "heart rate variability"[tiab] OR "oxygen saturation"[tiab] OR SpO2[tiab] OR
  "blood pressure"[tiab] OR "ambulatory blood pressure"[tiab] OR "energy expenditure"[tiab] OR MET[tiab] OR METs[tiab] OR
  CPET[tiab] OR "cardiopulmonary exercise test"[tiab] OR
  "six-minute walk test"[tiab] OR "6-minute walk test"[tiab] OR 6MWT[tiab] OR step test[tiab] OR
  PACER[tiab] OR FitnessGram[tiab] OR "shuttle run"[tiab] OR "beep test"[tiab] OR
  handgrip[tiab] OR "grip strength"[tiab] OR "sit and reach"[tiab] OR
  DXA[tiab] OR DEXA[tiab] OR "dual energy x ray absorptiometry"[tiab] OR
  skinfold*[tiab] OR "bioelectrical impedance"[tiab] OR BIA[tiab] OR
  "waist circumference"[tiab] OR "waist-to-hip ratio"[tiab] OR WHR[tiab] OR
  "exercise prescription"[tiab] OR "physical activity prescription"[tiab] OR
  "exercise referral"[tiab] OR "Green Prescription"[tiab] OR
  "Exercise is Medicine"[tiab] OR EIM[tiab] OR
  "health coaching"[tiab] OR "lifestyle counseling"[tiab] OR "lifestyle counselling"[tiab] OR
  "sedentary behavior"[tiab] OR "sedentary behaviour"[tiab] OR "sedentary time"[tiab] OR "screen time"[tiab]
)

### 典型期刊



---

## 4. 运动基础科学
**Exercise and Sport Science Fundamentals**

### 覆盖范围
- **运动生理学**：心肺功能、肌肉代谢、能量系统、VO2max
- **运动营养学**：补剂、水合、宏量营养素、能量平衡
- **运动神经科学**：运动控制、运动学习、神经可塑性、协调性
- **生物力学**：步态分析、运动学、动力学、肌电图(EMG)
- **生物化学**：运动生化指标、代谢组学

### MeSH主题词

( Sports[mh] OR Athletes[mh] OR Athletic Performance[mh] OR Exercise[mh] OR Motor Activity[mh] OR Physical Exertion[mh] OR Physical Fitness[mh] OR sport*[tiab] OR athlete*[tiab] OR exercis*[tiab] OR "physical activ*"[tiab] OR "resistance training"[tiab] OR "strength training"[tiab] OR "endurance training"[tiab] OR "aerobic training"[tiab] OR "interval training"[tiab] OR "high-intensity interval"[tiab] OR HIIT[tiab] OR "sprint interval"[tiab] OR SIT[tiab] OR plyometric*[tiab] OR "concurrent training"[tiab] OR periodization[tiab] OR taper*[tiab] OR (Animals[mh] AND (treadmill[tiab] OR wheel run*[tiab] OR voluntary running[tiab] OR forced running[tiab] OR swim training[tiab] OR swimming training[tiab] OR ladder climb*[tiab])) ) AND ( Exercise/physiology[mh] OR Oxygen Consumption[mh] OR Energy Metabolism[mh] OR Muscle, Skeletal/physiology[mh] OR Muscle, Skeletal/metabolism[mh] OR Muscle Contraction[mh] OR Muscle Fatigue[mh] OR Mitochondria, Muscle[mh] OR Lactic Acid[mh] OR Nervous System Physiological Phenomena[mh] OR Neuronal Plasticity[mh] OR Psychomotor Performance[mh] OR Autonomic Nervous System[mh] OR Electromyography[mh] OR Electroencephalography[mh] OR Transcranial Magnetic Stimulation[mh] OR Spectroscopy, Near-Infrared[mh] OR Magnetic Resonance Imaging[mh] OR Diffusion Tensor Imaging[mh] OR Brain Mapping[mh] OR Biomechanical Phenomena[mh] OR Gait[mh] OR Locomotion[mh] OR Posture[mh] OR Range of Motion, Articular[mh] OR Nutritional Physiological Phenomena[mh] OR Diet[mh] OR Dietary Supplements[mh] OR Glycogen[mh] OR Dietary Carbohydrates[mh] OR Dietary Proteins[mh] OR Amino Acids, Branched-Chain[mh] OR Caffeine[mh] OR Creatine[mh] OR Sodium Bicarbonate[mh] OR Nitrates[mh] OR Water-Electrolyte Balance[mh] OR Dehydration[mh] OR Rehydration Solutions[mh] OR "mitochondrial biogenesis"[tiab] OR "oxidative phosphorylation"[tiab] OR "substrate oxidation"[tiab] OR "glycogen resynthesis"[tiab] OR "insulin sensitivity"[tiab] OR GLUT4[tiab] OR "glucose uptake"[tiab] OR AMPK[tiab] OR mTOR[tiab] OR "PGC-1α"[tiab] OR "PGC-1a"[tiab] OR SIRT1[tiab] OR BDNF[tiab] OR VEGF[tiab] OR myokine*[tiab] OR irisin[tiab] OR FNDC5[tiab] OR adiponectin[tiab] OR leptin[tiab] OR testosterone[tiab] OR cortisol[tiab] OR "growth hormone"[tiab] OR "IGF-1"[tiab] OR kinematic*[tiab] OR kinetic*[tiab] OR "inverse dynamics"[tiab] OR "force plate"[tiab] OR "force plates"[tiab] OR "force platform"[tiab] OR "ground reaction force*"[tiab] OR "center of pressure"[tiab] OR CoP[tiab] OR "musculoskeletal model*"[tiab] OR OpenSim[tiab] OR "motion capture"[tiab] OR markerless[tiab] OR electromyograph*[tiab] OR EMG[tiab] OR "ultrasound elastography"[tiab] OR elastograph*[tiab] OR "pennation angle"[tiab] OR "fascicle length"[tiab] OR VO2max[tiab] OR VO2peak[tiab] OR "oxygen uptake"[tiab] OR "lactate threshold"[tiab] OR "critical power"[tiab] OR "critical speed"[tiab] OR "creatine kinase"[tiab] OR myoglobin[tiab] OR "C-reactive protein"[tiab] OR DOMS[tiab] ) NOT ( Transportation[mh] OR Commuting[mh] OR Urban Health[mh] OR "walkability"[tiab] OR "public transport"[tiab] OR "community vitality"[tiab] OR policy[tiab] OR Health Promotion[mh] OR Health Education[mh] OR "study protocol"[tiab] OR protocol[tiab] OR "scoping review"[tiab] OR Questionnaires[mh] OR validation[tiab] OR reliability[tiab] OR psychometric*[tiab] OR Cats[mh] OR Dogs[mh] OR Veterinary Medicine[mh] OR "training cohort"[tiab] OR "training set"[tiab] OR "training data"[tiab] OR "model training"[tiab] OR "machine learning"[tiab] OR sauna[tiab] OR "passive heating"[tiab] OR "hot water immersion"[tiab] )

### 典型期刊


---

## 5. 运动医学与康复
**Sports Medicine and Rehabilitation**



### MeSH主题词

(
  Sports[mh] OR Sports Medicine[mh] OR Athletes[mh] OR Athletic Injuries[mh] OR Athletic Performance[mh] OR
  Exercise[mh] OR Motor Activity[mh] OR Physical Fitness[mh] OR
  Rehabilitation[mh] OR Exercise Therapy[mh] OR Physical Therapy Modalities[mh] OR Orthopedic Procedures[mh] OR Arthroscopy[mh] OR
  Brain Concussion[mh] OR Post-Concussion Syndrome[mh] OR
  Tendinopathy[mh] OR Tendon Injuries[mh] OR Rotator Cuff Injuries[mh] OR
  Anterior Cruciate Ligament Injuries[mh] OR Anterior Cruciate Ligament Reconstruction[mh] OR
  Knee Injuries[mh] OR Shoulder Injuries[mh] OR Ankle Injuries[mh] OR Hip Injuries[mh] OR
  Sprains and Strains[mh] OR Fractures, Stress[mh]
  OR
  sport*[tiab] OR athlete*[tiab] OR "sports injur*"[tiab] OR "athletic injur*"[tiab] OR
  "return to play"[tiab] OR "return to sport"[tiab] OR "injury prevention"[tiab] OR
  "blood flow restriction"[tiab] OR KAATSU[tiab] OR ESWT[tiab] OR "shock wave therapy"[tiab] OR
  NMES[tiab] OR TENS[tiab] OR "manual therapy"[tiab] OR "foam rolling"[tiab] OR taping[tiab] OR "kinesio tap*"[tiab] OR
  "compression garment*"[tiab]
)
NOT
(
  Arthroplasty, Replacement, Hip[mh] OR Arthroplasty, Replacement, Knee[mh] OR
  "total hip arthroplasty"[tiab] OR THA[tiab] OR "total knee arthroplasty"[tiab] OR TKA[tiab] OR
  Kyphoplasty[mh] OR Vertebroplasty[mh] OR Spinal Fusion[mh] OR Arthrodesis[mh] OR
  Hip Fractures[mh] OR "fragility fracture*"[tiab] OR osteoporos*[tiab] OR "vertebral compression fracture*"[tiab] OR
  Diabetic Foot[mh] OR "diabetic foot"[tiab] OR Charcot Joint[mh] OR "Charcot"[tiab] OR
  Podiatry[mh] OR Dentistry[mh] OR Eye Diseases[mh] OR Amputation[mh]
  OR
  Accidents, Traffic[mh] OR "road traffic"[tiab] OR "traffic accident*"[tiab] OR "road accident*"[tiab] OR "road crash*"[tiab] OR
  motorcycl*[tiab] OR "motor vehicle*"[tiab] OR "vehicle occupant*"[tiab] OR pedestrian*[tiab] OR
  seatbelt*[tiab] OR "seat belt*"[tiab] OR "child restraint*"[tiab] OR
  "road safety"[tiab] OR "traffic police"[tiab] OR roadside[tiab] OR "Sport Utility Vehicle*"[tiab] OR SUV[tiab]
)


### 典型期刊

---

## 6. 运动心理
**Sport Psychology**

### MeSH主题词
```

(
  "Sports/psychology"[mh] OR "Athletes/psychology"[mh] OR "Athletic Performance/psychology"[mh] OR
  "Motor Skills/psychology"[mh] OR "Exercise/psychology"[mh] OR "Doping in Sports"[mh] OR
  "sport psychology"[tiab] OR "sports psychology"[tiab] OR "performance psychology"[tiab] OR "applied sport psychology"[tiab] OR
  "psychological skills training"[tiab] OR "mental skills training"[tiab] OR
  "mental toughness"[tiab] OR "competitive anxiety"[tiab] OR "sport anxiety"[tiab] OR CSAI-2[tiab] OR
  "choking under pressure"[tiab] OR "quiet eye"[tiab] OR "attentional focus"[tiab] OR
  "self-talk"[tiab] OR PETTLEP[tiab] OR "sport imagery"[tiab] OR
  "goal setting in sport"[tiab] OR "goal-setting in sport"[tiab] OR
  "coach-athlete relationship"[tiab] OR
  "motivational climate in sport"[tiab] OR "motivational climate for sport"[tiab] OR
  "team cohesion in sport"[tiab] OR "group cohesion in sport"[tiab] OR "Group Environment Questionnaire"[tiab] OR
  "collective efficacy in sport"[tiab] OR
  "athletic identity"[tiab] OR "athlete burnout"[tiab] OR ABQ[tiab] OR
  "overtraining syndrome"[tiab] OR
  "athlete sleep"[tiab] OR "sleep in athletes"[tiab] OR
  "psychological readiness to return to sport"[tiab] OR "fear of re-injury"[tiab] OR kinesiophobia[tiab] OR "ACL-RSI"[tiab] OR "I-PRRS"[tiab] OR
  "female athlete triad"[tiab] OR "relative energy deficiency in sport"[tiab] OR "RED-S"[tiab] OR
  "disordered eating in athletes"[tiab] OR "eating disorder in athletes"[tiab] OR
  "sport confidence"[tiab] OR "State Sport-Confidence Inventory"[tiab] OR SSCI[tiab] OR
  "Athletic Coping Skills Inventory"[tiab] OR ACSI-28[tiab] OR
  "pre-performance routine"[tiab] OR PPR[tiab] OR
  "Mindfulness-Acceptance-Commitment"[tiab] OR "Mindfulness Sport Performance Enhancement"[tiab] OR MSPE[tiab] OR
  "Profile of Mood States"[tiab] OR POMS[tiab] OR "Brunel Mood Scale"[tiab] OR BRUMS[tiab] OR
  "sport resilience"[tiab] OR "resilience in sport"[tiab] OR "grit in sport"[tiab] OR "Grit-S"[tiab] OR
  TEOSQ[tiab] OR POSQ[tiab] OR
  "perceptual-cognitive"[tiab] OR "gaze behavior in sport"[tiab] OR "visual search in sport"[tiab] OR "anticipation skill"[tiab] OR "anticipation skills"[tiab] OR
  "flow in sport"[tiab] OR "flow state in sport"[tiab] OR
  yips[tiab] OR "clutch performance"[tiab] OR
  "SMHAT-1"[tiab] OR "SMHRT-1"[tiab] OR
  "harassment in sport"[tiab] OR "abuse in sport"[tiab] OR "safeguarding in sport"[tiab] OR "bullying in sport"[tiab] OR
  "student-athlete"[tiab] OR "collegiate athlete"[tiab] OR "elite athlete"[tiab] OR "professional athlete"[tiab] OR
  "para-athlete"[tiab] OR "parasport"[tiab] OR "para-sport"[tiab] OR Paralympic*[tiab] OR Olympic*[tiab] OR esport*[tiab] OR "Special Olympics"[tiab] OR "Deaflympics"[tiab]
)
NOT
(
  Semiconductors[mh] OR Nanoparticles[mh] OR Nanostructures[mh] OR Electrochemistry[mh] OR Catalysis[mh] OR
  Dentistry[mh] OR dental[tiab] OR orthodontic*[tiab] OR periodont*[tiab] OR
  perovskite*[tiab] OR graphene[tiab] OR MoS2[tiab] OR "thin film*"[tiab] OR electrode*[tiab] OR battery[tiab] OR batteries[tiab] OR supercapacitor*[tiab] OR photocataly*[tiab] OR electrocataly*[tiab] OR thermoelectric[tiab] OR "n-type"[tiab] OR "p-type"[tiab] OR doped[tiab] OR
  "satellite imagery"[tiab] OR "remote sensing"[tiab] OR UAV[tiab] OR drone[tiab] OR LiDAR[tiab] OR LIDAR[tiab] OR "PM2.5"[tiab] OR "PM 2.5"[tiab] OR "PM(2.5)"[tiab] OR
  "Mycobacterium avium"[tiab] OR "mitral annular calcification"[tiab] OR "microcystic adnexal carcinoma"[tiab] OR "mass attenuation coefficient"[tiab] OR
  chromatography[tiab] OR "HPLC"[tiab] OR "LC-MS"[tiab] OR "LC-MS/MS"[tiab] OR "mass spectrometr*"[tiab] OR
  "study protocol"[tiab] OR "trial protocol"[tiab] OR protocol[tiab] OR
  "population-based"[tiab] OR "community-dwelling"[tiab] OR "primary care"[tiab] OR "general practice"[tiab] OR pharmacy[tiab] OR
  pregnancy[tiab] OR pregnant[tiab] OR perinatal[tiab] OR postpartum[tiab] OR maternal[tiab] OR
  hypertension[tiab] OR diabetes[tiab] OR MELAS[tiab] OR nephrol*[tiab] OR renal[tiab] OR kidney[tiab] OR dialysis[tiab] OR hemodialysis[tiab]
)


```

### 典型期刊


---

## 7. 体育人文与社会科学
**Sports Humanities and Social Sciences**

### 覆盖范围
- **体育社会学**：体育参与、社会公平、性别与体育
- **体育伦理**：兴奋剂伦理、公平竞争、道德教育
- **体育政策**：公共政策、体育法律、健康促进
- **体育管理**：组织管理、赛事管理、体育经济
- **体育哲学/历史**：体育价值观、体育史、体育文化

### MeSH主题词
```

( "Sports/ethics"[mh] OR "Sports/economics"[mh] OR "Sports/organization and administration"[mh] OR "Sports/legislation and jurisprudence"[mh] OR "Doping in Sports/ethics"[mh] OR "Doping in Sports/legislation and jurisprudence"[mh] OR "Athletes/legislation and jurisprudence"[mh] OR "Recreation/organization and administration"[mh] OR "Physical Education and Training/organization and administration"[mh] OR "sociology of sport"[tiab] OR "sport sociology"[tiab] OR "philosophy of sport"[tiab] OR "sport philosophy"[tiab] OR "sports history"[tiab] OR "history of sport"[tiab] OR Olympism[tiab] OR "sport culture"[tiab] OR "sports culture"[tiab] OR "sport policy"[tiab] OR "sports policy"[tiab] OR "sport governance"[tiab] OR "sports governance"[tiab] OR "sport management"[tiab] OR "sports management"[tiab] OR "sport administration"[tiab] OR "sports administration"[tiab] OR "sport economics"[tiab] OR "sports economics"[tiab] OR "sport finance"[tiab] OR "sports finance"[tiab] OR "sport marketing"[tiab] OR "sports marketing"[tiab] OR "broadcast rights"[tiab] OR "media rights"[tiab] OR "sports journalism"[tiab] OR "sports media"[tiab] OR "sports law"[tiab] OR "sport law"[tiab] OR "sports integrity"[tiab] OR "match fixing"[tiab] OR "match-fixing"[tiab] OR "match manipulation"[tiab] OR "sports corruption"[tiab] OR "anti-doping policy"[tiab] OR "World Anti-Doping Code"[tiab] OR "WADA Code"[tiab] OR "therapeutic use exemption"[tiab] OR TUE[tiab] OR "athlete biological passport"[tiab] OR "biological passport"[tiab] OR "fair play"[tiab] OR "safeguarding in sport"[tiab] OR "abuse in sport"[tiab] OR "harassment in sport"[tiab] OR "bullying in sport"[tiab] OR "gender equity in sport"[tiab] OR "gender equality in sport"[tiab] OR "women in sport"[tiab] OR "transgender athlete*"[tiab] OR "intersex athlete*"[tiab] OR "DSD athlete*"[tiab] OR "Title IX"[tiab] OR "name image likeness"[tiab] OR "athlete rights"[tiab] OR "human rights in sport"[tiab] OR "athlete activism"[tiab] OR "sports diplomacy"[tiab] OR "sport tourism"[tiab] OR "sports tourism"[tiab] OR "sport mega-event"[tiab] OR "mega-event"[tiab] OR "mega event"[tiab] OR "Olympic legacy"[tiab] OR "World Cup legacy"[tiab] OR "fan engagement"[tiab] OR "sports fandom"[tiab] OR hooliganism[tiab] OR "fan violence"[tiab] OR NCAA[tiab] OR FIFA[tiab] OR "International Olympic Committee"[tiab] OR "salary cap"[tiab] OR "collective bargaining agreement"[tiab] OR "free agency"[tiab] OR "transfer portal"[tiab] OR "transfer window"[tiab] OR "financial fair play"[tiab] OR "Paralympic classification"[tiab] OR "athlete migration"[tiab] OR "sport migration"[tiab] OR "stadium financing"[tiab] OR "stadium subsidy"[tiab] OR "arena financing"[tiab] OR "sportswashing"[tiab] OR "SafeSport"[tiab] OR "sport participation"[tiab] OR "sports participation"[tiab] OR "community sport"[tiab] OR "grassroots sport"[tiab] OR "youth sport"[tiab] OR "equal pay in sport"[tiab] OR "gender pay gap in sport"[tiab] OR "athlete welfare"[tiab] OR "athlete wellbeing"[tiab] OR "athlete well-being"[tiab] OR "sport commercialization"[tiab] OR "sports commercialization"[tiab] ) NOT ( cholangiograph*[tiab] OR cholecystect*[tiab] OR biliary[tiab] OR "bile duct"[tiab] OR gallbladder[tiab] OR intraoperative[tiab] OR perioperative[tiab] OR anesthe*[tiab] OR "nil per os"[tiab] OR NPO[tiab] OR "Index of Item-Objective Congruence"[tiab] )

```

### 典型期刊

---

## 8. 体育工程与技术
**Sports Engineering and Technology**

### 覆盖范围
- 体育器材设计与测试
- 防护装备（头盔、护具）
- 矫形器械
- 可穿戴设备与传感器
- **运动数据分析与建模**（运动表现分析、机器学习、体育大数据）
- **体育统计与数据科学**（比赛数据分析、战术分析、球员评估）
- 运动视频分析与计算机视觉
- 有限元分析(FEA)

### MeSH主题词

(
  "Sports"[mh] OR "Athletic Performance"[mh] OR "Athletes"[mh] OR "Athletic Equipment"[mh] OR
  sport*[ti] OR athlete*[ti] OR athletic[ti] OR
  football[ti] OR soccer[ti] OR basketball[ti] OR rugby[ti] OR hockey[ti] OR cricket[ti] OR volleyball[ti] OR tennis[ti] OR baseball[ti] OR handball[ti] OR futsal[ti] OR
  "track and field"[ti] OR athletics[ti] OR marathon[ti] OR triathlon[ti] OR cycling[ti] OR rowing[ti] OR swimming[ti] OR "open water"[ti] OR
  skiing[ti] OR snowboard*[ti] OR "speed skating"[ti] OR "figure skating"[ti] OR biathlon[ti] OR bobsleigh[ti] OR luge[ti] OR skeleton[ti] OR curling[ti] OR
  "table tennis"[ti] OR badminton[ti] OR squash[ti] OR padel[ti] OR pickleball[ti] OR golf[ti] OR fencing[ti] OR gymnastics[ti] OR
  "martial arts"[ti] OR boxing[ti] OR wrestling[ti] OR surfing[ti] OR sailing[ti] OR canoe*[ti] OR kayak*[ti] OR equestrian[ti] OR Paralympic*[ti] OR Olympic*[ti]
)
AND
(
  "Biomechanical Phenomena"[mh] OR "Motion Capture"[mh] OR "Gait Analysis"[mh] OR
  "Image Processing, Computer-Assisted"[mh] OR "Pattern Recognition, Automated"[mh] OR
  "Computer Simulation"[mh] OR "Finite Element Analysis"[mh] OR
  "Equipment Design"[mh] OR "Equipment Failure Analysis"[mh] OR "Materials Testing"[mh] OR
  "Protective Devices"[mh] OR "Head Protective Devices"[mh] OR "Helmets"[mh] OR "Mouth Protectors"[mh] OR
  "Orthotic Devices"[mh] OR "Footwear"[mh] OR
  "Wearable Electronic Devices"[mh] OR "Accelerometry"[mh] OR "Actigraphy"[mh] OR
  "Electromyography"[mh] OR "Electrocardiography"[mh] OR "Photoplethysmography"[mh] OR
  "Artificial Intelligence"[mh] OR "Machine Learning"[mh] OR "Deep Learning"[mh] OR
  "Neural Networks, Computer"[mh] OR "Signal Processing, Computer-Assisted"[mh]
  OR
  "sports engineering"[tiab] OR "sport engineering"[tiab] OR
  "sports technology"[tiab] OR "sport technology"[tiab] OR
  "performance analysis"[tiab] OR "match analysis"[tiab] OR "tactical analysis"[tiab] OR
  "sports analytics"[tiab] OR "sport analytics"[tiab] OR "sports statistics"[tiab] OR "sport statistics"[tiab] OR
  "player evaluation"[tiab] OR "player tracking"[tiab] OR "athlete tracking"[tiab] OR "ball tracking"[tiab] OR
  "optical tracking"[tiab] OR "radio-based tracking"[tiab] OR EPTS[tiab] OR
  "goal-line technology"[tiab] OR "video assistant referee"[tiab] OR VAR[tiab] OR "semi-automated offside"[tiab] OR "Hawk-Eye"[tiab] OR
  "markerless motion capture"[tiab] OR "pose estimation"[tiab] OR OpenPose[tiab] OR AlphaPose[tiab] OR DeepLabCut[tiab] OR MediaPipe[tiab] OR
  "skeleton-based"[tiab] OR SMPL[tiab] OR "SMPL-X"[tiab] OR OpenCap[tiab] OR
  "kinematic analysis"[tiab] OR photogrammetry[tiab] OR "high-speed camera"[tiab] OR "depth camera"[tiab] OR "time-of-flight"[tiab] OR Kinect[tiab] OR
  "force plate"[tiab] OR "force platform"[tiab] OR "pressure insole*"[tiab] OR "plantar pressure"[tiab] OR "pressure mapping"[tiab] OR
  GPS[tiab] OR "global positioning system"[tiab] OR GNSS[tiab] OR UWB[tiab] OR "ultra-wideband"[tiab] OR RFID[tiab] OR LPS[tiab] OR "local positioning system"[tiab] OR
  IMU[tiab] OR "inertial measurement unit"[tiab] OR acceleromet*[tiab] OR gyroscope*[tiab] OR magnetometer*[tiab] OR
  "sensor fusion"[tiab] OR "Kalman filter"[tiab] OR "extended Kalman"[tiab] OR "particle filter"[tiab] OR
  EMG[tiab] OR ECG[tiab] OR PPG[tiab] OR NIRS[tiab] OR fNIRS[tiab] OR sEMG[tiab] OR
  "finite element analysis"[tiab] OR FEA[tiab] OR "finite element model*"[tiab] OR
  "head injury criterion"[tiab] OR HIC[tiab] OR "brain injury criterion"[tiab] OR
  "maximum principal strain"[tiab] OR MPS[tiab] OR CSDM[tiab] OR
  "drop test"[tiab] OR "impact test"[tiab] OR "impact attenuation"[tiab] OR "shock absorption"[tiab] OR "energy absorption"[tiab] OR
  Abaqus[tiab] OR "LS-DYNA"[tiab] OR Ansys[tiab] OR MADYMO[tiab] OR "explicit dynamics"[tiab] OR "topology optimization"[tiab] OR
  CFD[tiab] OR "computational fluid dynamics"[tiab] OR aerodynamics[tiab] OR "wind tunnel"[tiab] OR
  drag[tiab] OR lift[tiab] OR "Magnus effect"[tiab] OR "spin rate"[tiab] OR "ball trajectory"[tiab] OR "ball flight"[tiab] OR
  "ball bounce"[tiab] OR "coefficient of restitution"[tiab] OR COR[tiab] OR seam[tiab] OR dimples[tiab] OR "ski wax"[tiab] OR hydrodynamics[tiab] OR
  "sports equipment"[tiab] OR "sport equipment"[tiab] OR "athletic equipment"[tiab] OR
  "equipment testing"[tiab] OR "equipment design"[tiab] OR "equipment safety"[tiab] OR
  composite*[tiab] OR "carbon fiber"[tiab] OR "additive manufactur*"[tiab] OR "3D print*"[tiab] OR lattice[tiab] OR auxetic*[tiab] OR foam[tiab] OR EVA[tiab] OR TPU[tiab] OR viscoelastic*[tiab] OR
  helmet*[tiab] OR headgear[tiab] OR mouthguard[tiab] OR "shin guard*"[tiab] OR "back protector*"[tiab] OR "spine protector*"[tiab] OR "shoulder pad*"[tiab] OR
  "knee brace"[tiab] OR "ankle brace"[tiab] OR orthotic*[tiab] OR orthoses[tiab] OR orthosis[tiab] OR exoskeleton*[tiab] OR exosuit*[tiab] OR
  footwear[tiab] OR insole*[tiab] OR cleat*[tiab] OR spike*[tiab] OR "shoe midsole"[tiab] OR "stack height"[tiab] OR "heel-to-toe drop"[tiab] OR "plate stiffness"[tiab] OR "carbon plate"[tiab]
  OR
  "playing surface"[tiab] OR "court surface"[tiab] OR "track surface"[tiab] OR "artificial turf"[tiab] OR "synthetic turf"[tiab] OR
  "force reduction"[tiab] OR "vertical deformation"[tiab] OR "energy restitution"[tiab] OR "FIFA Quality"[tiab] OR "World Rugby Regulation 22"[tiab] OR "World Athletics"[tiab]
  OR
  "smartwatch"[tiab] OR "smart garment"[tiab] OR "smart clothing"[tiab] OR "e-textile*"[tiab] OR "textile sensor*"[tiab] OR "conductive fabric"[tiab] OR "edge computing"[tiab]
  OR
  "player load"[tiab] OR "training load"[tiab] OR "expected goals"[tiab] OR "expected threat"[tiab] OR "expected possession value"[tiab] OR
  "win probability"[tiab] OR "plus-minus"[tiab] OR "passing network"[tiab] OR "possession network"[tiab] OR
  "Second Spectrum"[tiab] OR SportVU[tiab] OR TRACAB[tiab] OR Catapult[tiab] OR STATSports[tiab] OR WIMU[tiab] OR Kinexon[tiab]
  OR
  "string tension"[tiab] OR "racket stiffness"[tiab] OR "bat vibration"[tiab] OR "sweet spot"[tiab] OR "moment of inertia"[tiab] OR MOI[tiab] OR
  "smart ball"[tiab] OR "instrumented ball"[tiab] OR "sensorized ball"[tiab]
  OR
  "ergometer"[tiab] OR "rowing ergometer"[tiab] OR "cycle ergometer"[tiab] OR "ski ergometer"[tiab] OR "skating treadmill"[tiab] OR
  "pitching machine"[tiab] OR "ball machine"[tiab]
)


### 典型期刊


---



