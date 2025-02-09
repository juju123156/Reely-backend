package com.reely.controller;

import java.util.List;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import com.reely.dto.SettingDto;
import com.reely.service.SettingService;

@RestController
@RequestMapping("/setting")
public class SettingController {
    
    @Autowired
    SettingService settingService;

    @Autowired
    public SettingController(SettingService settingService) {
        this.settingService = settingService;
    }

    @GetMapping(value = "/faq/getFaqList")
    public ResponseEntity<List<SettingDto>> getFaqList(){
        List<SettingDto> faqList = settingService.getFaqList();
        return new ResponseEntity<>(faqList, HttpStatus.OK);
    }

    @GetMapping(value = "/terms/getTermsList")
    public ResponseEntity<List<SettingDto>> getTermsList(){
        List<SettingDto> termsList = settingService.getTermsList();
        return new ResponseEntity<>(termsList, HttpStatus.OK);
    }

    @GetMapping(value = "/serviceInfo/getLatestVersion")
    public ResponseEntity<List<SettingDto>> getLatestVersion(){
        List<SettingDto> latestVersion = settingService.getLatestVersion();
            System.out.printf(latestVersion.toString());

        return new ResponseEntity<>(latestVersion, HttpStatus.OK);
    }

}
