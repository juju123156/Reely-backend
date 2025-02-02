package com.reely.dto;

import java.util.List;

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
    private List<SettingDto> faqList;
}
