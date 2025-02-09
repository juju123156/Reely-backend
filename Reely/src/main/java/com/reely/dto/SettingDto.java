package com.reely.dto;

import lombok.Getter;
import lombok.Setter;
import lombok.ToString;

@Getter
@Setter
@ToString
public class SettingDto {
    private String faqId;
    private String faqTitle;
    private String faqContents;
    private String termsId;
    private String termsTitle;
    private String termsContents;
    private String latestVersion;
    
}
